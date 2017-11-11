""" DCN+ Query Document Encoder/Decoder [1]

NOTE: query always comes before document in function arguments and returns

[1] DCN+: Mixed Objective and Deep Residual Coattention for Question Answering, 
        Xiong et al, https://arxiv.org/abs/1711.00106
"""

import tensorflow as tf

def encode(state_size, query, query_length, document, document_length):
    """ DCN+ encoder that encodes queries and documents into one representation.

    N = Batch size
    D = Document max length
    Q = Query max length
    H = State size
    R = Word embedding size

    Args:
        state_size: A scalar integer. State size of RNN cell encoders.
        query: A tensor of rank 3, shape [N, Q, R].
        query_length: A tensor of rank 1, shape [N]. Lengths of queries.
        document: A tensor of rank 3, shape [N, D, R]. 
        document_length: A tensor of rank 1, shape [N]. Lengths of documents.
    
    Returns:
        Merged representation of query and document in document space, shape [N, D, 2H].
    """

    def get_cell():
        cell_type = tf.contrib.rnn.LSTMCell
        return cell_type(num_units=state_size)

    with tf.variable_scope('encoder'):
        query_encoding, document_encoding = query_document_encoder(get_cell(), get_cell(), query, query_length, document, document_length)

    with tf.variable_scope('coattention_1'):
        summary_q_1, summary_d_1, coattention_d_1 = coattention(query_encoding, query_length, document_encoding, document_length, sentinel=True)
    
    with tf.variable_scope('summary_encoder'):
        summary_q_encoding, summary_d_encoding = query_document_encoder(get_cell(), get_cell(), summary_q_1, query_length, summary_d_1, document_length)

    with tf.variable_scope('coattention_2'): 
        _, summary_d_2, coattention_d_2 = coattention(summary_q_encoding, query_length, summary_d_encoding, document_length)

    document_representations = [
        document_encoding,  # E^D_1
        summary_d_encoding, # E^D_2
        summary_d_1,        # S^D_1
        summary_d_2,        # S^D_2
        coattention_d_1,    # C^D_1
        coattention_d_2,    # C^D_2
    ]

    with tf.variable_scope('final_encoder'):
        document_representation = tf.concat(document_representations, 2)
        outputs, _ = tf.nn.bidirectional_dynamic_rnn(
            cell_fw = get_cell(),
            cell_bw = get_cell(),
            dtype = tf.float32,
            inputs = document_representation,
            sequence_length = document_length,
        )
        encoding = tf.concat(outputs, 2)
    return encoding  # N x D x 2H


def query_document_encoder(cell_fw, cell_bw, query, query_length, document, document_length):
    """ DCN+ Query Document Encoder layer.
    
    Forward and backward cells are shared between the bidirectional query and document encoders. 
    The document encoding passes through an additional dense layer with tanh activation.

    Args:
        cell_fw: RNNCell for forward direction encoding.
        cell_bw: RNNCell for backward direction encoding.
        query: A tensor of rank 3, shape [N, Q, 2H].
        query_length: A tensor of rank 1, shape [N]. Lengths of queries.
        document: A tensor of rank 3, shape [N, D, 2H].
        document_length: A tensor of rank 1, shape [N]. Lengths of documents.
    Returns:
        A tuple containing
            encoding of query, shape [N, Q, 2H]
            encoding of document, shape [N, D, 2H]
    """
    query_fw_bw_encodings, _ = tf.nn.bidirectional_dynamic_rnn(
        cell_fw = cell_fw,
        cell_bw = cell_bw,
        dtype = tf.float32,
        inputs = query,
        sequence_length = query_length
    )
    query_encoding = tf.concat(query_fw_bw_encodings, 2)
    query_encoding = tf.layers.dense(query_encoding, tf.shape(query_encoding)[2], activation=tf.tanh)

    document_fw_bw_encodings, _ = tf.nn.bidirectional_dynamic_rnn(
        cell_fw = cell_fw,
        cell_bw = cell_bw,
        dtype = tf.float32,
        inputs = document,
        sequence_length = document_length
    )
    document_encoding = tf.concat(document_fw_bw_encodings, 2)

    return query_encoding, document_encoding


def maybe_mask_affinity(affinity, sequence_length, affinity_mask_value=float('-inf')):
    """ Masks affinity along its third dimension with `affinity_mask_value`.

    Used for masking entries of sequences longer than `sequence_length` prior to 
    applying softmax.

    Args:
        affinity: A tensor of rank 3, of shape [N, D or Q, Q or D] where attention logits are in the second dimension.
        sequence_length: A tensor of rank 1, of shape [N]. Lengths of second dimension of the affinity.
        affinity_mask_value: (optional) Value to mask affinity with.
    
    Returns:
        Masked affinity
    """
    if sequence_length is None:
        return affinity
    score_mask = tf.sequence_mask(sequence_length, maxlen=tf.shape(affinity)[1])
    score_mask = tf.tile(tf.expand_dims(score_mask, 2), (1, 1, tf.shape(affinity)[2]))
    affinity_mask_values = affinity_mask_value * tf.ones_like(affinity)
    return tf.where(score_mask, affinity, affinity_mask_values)


def add_sentinel(encoding):
    # TODO will need to add +1 to first coattention layer calculation
    pass


def remove_sentinel(encoding):
    pass


def coattention(query, query_length, document, document_length, sentinel=False):
    """ DCN+ Coattention layer.
    
    Args:
        query: A tensor of rank 3, shape [N, Q, 2H].
        query_length: A tensor of rank 1, shape [N]. Lengths of queries.
        document: A tensor of rank 3, shape [N, D, 2H].
        document_length: A tensor of rank 1, shape [N]. Lengths of documents.
        sentinel: Scalar boolean. If True, concatenate a sentinel vector to query and document.

    Returns:
        A tuple containing:
            summary matrix of the query, shape [N, Q, 2H]
            summary matrix of the document, shape [N, D, 2H]
            coattention matrix of the document and query in document space, shape [N, D, 2H]
    
    * TODO add sentinel
    """

    """
    The symbols in [1] correspond to the following identifiers
        A   = affinity
        A^T = affinity_t
        E^Q = query
        E^D = document
        S^Q = summary_q
        S^D = summary_d
        C^D = coattention_d
    
    The indices in Einstein summation notation correspond to
        n = batch dimension
        d = document dimension
        q = query dimension
        h = hidden state dimension
    """
    # TODO make sure masking is enough
        
    unmasked_affinity = tf.einsum('ndh,nqh->ndq', document, query)  # N x D x Q
    affinity = maybe_mask_affinity(unmasked_affinity, document_length)
    attention_p = tf.nn.softmax(affinity, dim=1)  # N x D x Q
    affinity_t = maybe_mask_affinity(tf.transpose(unmasked_affinity, [0, 2, 1]), query_length)
    attention_q = tf.nn.softmax(affinity_t, dim=1)  # N x Q x D
    summary_q = tf.einsum('ndh,ndq->nqh', document, attention_p)  # N x 2H x Q
    summary_d = tf.einsum('nqh,nqd->ndh', query, attention_q)  # N x 2H x D
    coattention_d = tf.einsum('nqh,nqd->ndh', summary_q, attention_q) # N x D x 2H
    return summary_q, summary_d, coattention_d


def decode(encoding):
    """ Decodes encoding to logits used to find answer span

    Args:
        encoding: Document representation, shape [N, D, ?].
    
    Returns:
        A tuple containing
            Logit for answer span start position, shape [N]
            Logit for answer span end position, shape [N]
    """
    
    with tf.variable_scope('decode_start'):
        start_logit = tf.layers.dense(encoding, 1)
        start_logit = tf.squeeze(start_logit)
    
    # TODO condition decode_end on decode_start
    with tf.variable_scope('decode_end'):
        end_logit = tf.layers.dense(encoding, 1)
        end_logit = tf.squeeze(end_logit)

    return start_logit, end_logit
