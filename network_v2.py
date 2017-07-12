import re
import tensorflow as tf
import numpy as np


# Constants describing the training process.
MOVING_AVERAGE_DECAY = 0.9999    # The decay to use for the moving average.
NUM_EPOCHS_PER_DECAY = 100  # Epochs after which learning rate decays.
LEARNING_RATE_DECAY_FACTOR = 0.1 # Learning rate decay factor.
INITIAL_LEARNING_RATE = 3.   # Initial learning rate.

# If a model is trained with multiple GPUs, prefix all Op names with tower_name
# to differentiate the operations. Note that this prefix is removed from the
# names of the summaries when visualizing a model.
TOWER_NAME = 'tower'

def _activation_summary(x):
    """Helper to create summaries for activations.

     Creates a summary that provides a histogram of activations.
     Creates a summary that measures the sparsity of activations.

     Args:
       x: Tensor
     Returns:
       nothing
    """
    # Remove 'tower_[0-9]/' from the name in case this is a multi-GPU training
    # session. This helps the clarity of presentation on tensorboard.
    tensor_name = re.sub('%s_[0-9]*/' % TOWER_NAME, '', x.op.name)
    tf.summary.histogram(tensor_name + '/activations', x)
    tf.summary.scalar(tensor_name + '/sparsity', tf.nn.zero_fraction(x))

def _activation_image_summary(pool, nFeatures=None):
    """ Helper to show images of activation maps in summary.

    Args:
        pool: Tensor, 4-d output of conv/pool layer
        nFeatures: int, # of featuers to display, Optional, default is half of features depth.
    Returns:
        Nothing
    """
    # Remove 'tower_[0-9]/' from the name in case this is a multi-GPU training
    # session. This helps the clarity of presentation on tensorboard.
    # taking only first 3 images from batch

    if nFeatures is None:
        # nFeatures = int(pool.shape[-1].value /2)
        nFeatures = -1
    tensor_name = re.sub('%s_[0-9]*/' % TOWER_NAME, '', pool.op.name)
    for ind in xrange(3):
        map = tf.slice(pool, (ind,0,0,0),(1, -1, -1, nFeatures))
        # print('activation map shape: %s' %(format(map.shape)))
        map = tf.reshape(map, (map.shape[1].value, map.shape[2].value, map.shape[-1].value))
        map = tf.transpose(map, (2, 0 , 1))
        map = tf.reshape(map, (-1, map.shape[1].value, map.shape[2].value, 1))
        # color_maps = tf.image.grayscale_to_rgb(map)
        # Tiling
        nOfSlices = map.shape[0].value
        n = int(np.ceil(np.sqrt(nOfSlices)))
        # padding by 4 pixels
        padding = [[0, n ** 2 - nOfSlices], [0, 4], [0, 4], [0, 0]]
        map_padded = tf.pad(map, paddings=padding)
        # reshaping and transposing gymnastics ...
        new_shape = (n, n) + (map_padded.shape[1].value, map_padded.shape[2].value, 1)
        map_padded = tf.reshape(map_padded, new_shape)
        map_padded = tf.transpose(map_padded, perm=(0, 2, 1, 3, 4))
        new_shape = (n * map_padded.shape[1].value, n * map_padded.shape[3].value, 1)
        map_tile = tf.reshape(map_padded, new_shape)
        # Convert to 4-d
        map_tile = tf.expand_dims(map_tile,0)
        map_tile = tf.log1p(map_tile)
        # Display feature maps
        tf.summary.image(tensor_name + '/map_slice_'+ str(ind), map_tile)

def _variable_on_cpu(name, shape, initializer):
    """Helper to create a Variable stored on CPU memory.

    Args:
      name: name of the variable
      shape: list of ints
      initializer: initializer for Variable

    Returns:
      Variable Tensor
    """

    with tf.device('/cpu:0'):
        dtype = tf.float32
        var = tf.get_variable(name, shape, initializer=initializer, dtype=dtype)
    return var

def _variable_with_weight_decay(name, shape, stddev, wd):
    """Helper to create an initialized Variable with weight decay.

    Note that the Variable is initialized with a truncated normal distribution.
    A weight decay is added only if one is specified.

    Args:
    name: name of the variable
    shape: list of ints
    stddev: standard deviation of a truncated Gaussian
    wd: add L2Loss weight decay multiplied by this float. If None, weight
        decay is not added for this Variable.

    Returns:
    Variable Tensor
    """
    dtype = tf.float32
    var = _variable_on_cpu(
      name,
      shape,
      tf.truncated_normal_initializer(stddev=stddev, dtype=dtype))
    if wd is not None:
        weight_decay = tf.multiply(tf.nn.l2_loss(var), wd, name='weight_loss')
        tf.add_to_collection('losses', weight_decay)
    return var

def inference(images, FLAGS):
    """Build the model.

    Args:
    images: Images returned from Dataset.train_image_label_batch
    num_classes: Number of classes in the classification model.

    Returns:
    Logits.
    """

    # We instantiate all variables using tf.get_variable() instead of
    # tf.Variable() in order to share variables across multiple GPU training runs.
    # If we only ran this model on a single GPU, we could simplify this function
    # by replacing all instances of tf.get_variable() with tf.Variable().


    # conv1
    with tf.variable_scope('conv1') as scope:
        kernel = _variable_with_weight_decay('weights',
                                             shape=[3, 3, 1, 64],
                                             stddev=5e-2,
                                             wd=0.0)
        conv = tf.nn.conv2d(images, kernel, [1, 1, 1, 1], padding='VALID')
        mean, var = tf.nn.moments(conv, axes=[0,1,2])
        conv = tf.nn.batch_normalization(conv, mean, var, None, None,1.e-4)
        biases = _variable_on_cpu('biases', [64], tf.constant_initializer(0.0))
        pre_activation = tf.nn.bias_add(conv, biases)
        conv1 = tf.nn.relu(pre_activation, name=scope.name)
        print("conv1 shape: %s" % (format(conv1.shape)))
        _activation_summary(conv1)
        _activation_image_summary(conv1)

    # conv2
    with tf.variable_scope('conv2') as scope:
        kernel = _variable_with_weight_decay('weights',
                                             shape=[3, 3, 64, 64],
                                             stddev=5e-2,
                                             wd=0.0)
        conv = tf.nn.conv2d(conv1, kernel, [1, 1, 1, 1], padding='VALID')
        mean, var = tf.nn.moments(conv, axes=[0, 1, 2])
        conv = tf.nn.batch_normalization(conv, mean, var, None, None,1.e-4)
        biases = _variable_on_cpu('biases', [64], tf.constant_initializer(0.0))
        pre_activation = tf.nn.bias_add(conv, biases)
        conv2 = tf.nn.relu(pre_activation, name=scope.name)
        print(scope.name+" shape: %s" % (format(conv2.shape)))
        _activation_summary(conv2)
        _activation_image_summary(conv2)

    # conv3
    with tf.variable_scope('conv3') as scope:
        kernel = _variable_with_weight_decay('weights',
                                             shape=[3, 3, 64, 64],
                                             stddev=5e-2,
                                             wd=0.0)
        conv = tf.nn.conv2d(conv2, kernel, [1, 1, 1, 1], padding='VALID')
        mean, var = tf.nn.moments(conv, axes=[0, 1, 2])
        conv = tf.nn.batch_normalization(conv, mean, var, None, None,1.e-4)
        biases = _variable_on_cpu('biases', [64], tf.constant_initializer(0.1))
        pre_activation = tf.nn.bias_add(conv, biases)
        conv3 = tf.nn.relu(pre_activation, name=scope.name)
        print(scope.name+" shape: %s" % (format(conv3.shape)))
        _activation_summary(conv3)
        _activation_image_summary(conv3)

    # conv4
    with tf.variable_scope('conv4') as scope:
        kernel = _variable_with_weight_decay('weights',
                                             shape=[3, 3, 64, 64],
                                             stddev=5e-2,
                                             wd=0.0)
        conv = tf.nn.conv2d(conv3, kernel, [1, 1, 1, 1], padding='VALID')
        mean, var = tf.nn.moments(conv, axes=[0, 1, 2])
        conv = tf.nn.batch_normalization(conv, mean, var, None, None,1.e-4)
        biases = _variable_on_cpu('biases', [64], tf.constant_initializer(0.1))
        pre_activation = tf.nn.bias_add(conv, biases)
        conv4 = tf.nn.relu(pre_activation, name=scope.name)
        print(scope.name+" shape: %s"  % (format(conv4.shape)))
        _activation_summary(conv4)
        _activation_image_summary(conv4)

    # conv5
    with tf.variable_scope('conv5') as scope:
        kernel = _variable_with_weight_decay('weights',
                                             shape=[3, 3, 64, 64],
                                             stddev=5e-2,
                                             wd=0.0)
        conv = tf.nn.conv2d(conv4, kernel, [1, 1, 1, 1], padding='VALID')
        mean, var = tf.nn.moments(conv, axes=[0, 1, 2])
        conv = tf.nn.batch_normalization(conv, mean, var, None, None, 1.e-4)
        biases = _variable_on_cpu('biases', [64], tf.constant_initializer(0.1))
        pre_activation = tf.nn.bias_add(conv, biases)
        conv5 = tf.nn.relu(pre_activation, name=scope.name)
        print(scope.name + " shape: %s" % (format(conv5.shape)))
        _activation_summary(conv5)
        _activation_image_summary(conv5)

    # conv6
    with tf.variable_scope('conv6') as scope:
        kernel = _variable_with_weight_decay('weights',
                                             shape=[2, 2, 64, 64],
                                             stddev=5e-2,
                                             wd=0.0)
        conv = tf.nn.conv2d(conv5, kernel, [1, 1, 1, 1], padding='VALID')
        mean, var = tf.nn.moments(conv, axes=[0, 1, 2])
        conv = tf.nn.batch_normalization(conv, mean, var, None, None,1.e-4)
        biases = _variable_on_cpu('biases', [64], tf.constant_initializer(0.1))
        pre_activation = tf.nn.bias_add(conv, biases)
        conv6 = tf.nn.relu(pre_activation, name=scope.name)
        _activation_summary(conv6)
        _activation_image_summary(conv6)
        print(scope.name + " shape: %s" (format(conv6.shape)))

    # conv7
    with tf.variable_scope('conv7') as scope:
        kernel = _variable_with_weight_decay('weights',
                                             shape=[2, 2, 64, 64],
                                             stddev=5e-2,
                                             wd=0.0)
        conv = tf.nn.conv2d(conv6, kernel, [1, 1, 1, 1], padding='VALID')
        mean, var = tf.nn.moments(conv, axes=[0, 1, 2])
        conv = tf.nn.batch_normalization(conv, mean, var, None, None,1.e-4)
        biases = _variable_on_cpu('biases', [64], tf.constant_initializer(0.1))
        pre_activation = tf.nn.bias_add(conv, biases)
        conv7 = tf.nn.relu(pre_activation, name=scope.name)
        _activation_summary(conv6)
        _activation_image_summary(conv6)
        print("conv3_post shape: %s" % (format(conv6.shape)))

    # pool global
    with tf.variable_scope('pool_global') as scope:
        pool_global = tf.nn.avg_pool(conv7, ksize=[1,2,2,1], strides=[1,2,2,1], padding='VALID', name=scope.name)
        _activation_image_summary(pool_global)
        print(scope.name+ " shape: %s" % (format(pool_global.shape)))

    # Fully Connected
    with tf.variable_scope('Fully_connected') as scope:
        # Move everything into depth so we can perform a single matrix multiply.
        reshape = tf.reshape(pool_global, [FLAGS.batch_size, -1])

        dim = reshape.get_shape()[1].value
        weights = _variable_with_weight_decay('weights', shape=[dim, 1024],
                                              stddev=0.04, wd=0.001)
        biases = _variable_on_cpu('biases', [1024], tf.constant_initializer(0.1))
        RELU = tf.nn.relu(tf.matmul(reshape, weights) + biases, name=scope.name)
        #dropout of neurons
        # keep_prob = tf.constant(0.5, dtype=tf.float32, name="drop_prob")
        # RELU3_dropout = tf.nn.dropout(RELU3, keep_prob)
        _activation_summary(RELU)


    # softmax linear
    with tf.variable_scope('softmax_linear') as scope:
        # linear layer(WX + b),
        # We don't apply softmax here because
        # tf.nn.sparse_softmax_cross_entropy_with_logits accepts the unscaled logits
        # and performs the softmax internally for efficiency.

        weights = _variable_with_weight_decay('weights', [1024, FLAGS.NUM_CLASSES],
                                              stddev=0.04, wd=0.0)
        biases = _variable_on_cpu('biases', [FLAGS.NUM_CLASSES],
                                  tf.constant_initializer(0.0))
        softmax_linear = tf.add(tf.matmul(RELU, weights), biases, name=scope.name)
        _activation_summary(softmax_linear)

    return softmax_linear

def loss(logits, labels):
    """Add L2Loss to all the trainable variables.

    Add summary for "Loss" and "Loss/avg".
    Args:
    logits: Logits from inference().
    labels: Labels returned by Dataset.train_image_label_batch

    Returns:
    Loss tensor of type float.
    """
    # Calculate the average cross entropy loss across the batch.
    labels = tf.cast(labels, tf.int64)
    labels = tf.argmax(labels, axis=1)
    cross_entropy = tf.nn.sparse_softmax_cross_entropy_with_logits(
      labels=labels, logits=logits, name='cross_entropy_per_example')
    cross_entropy_mean = tf.reduce_mean(cross_entropy, name='cross_entropy')
    tf.add_to_collection('losses', cross_entropy_mean)

    # The total loss is defined as the cross entropy loss plus all of the weight
    # decay terms (L2 loss).
    return tf.add_n(tf.get_collection('losses'), name='total_loss')

def _add_loss_summaries(total_loss):
    """Add summaries for losses in model.

    Generates moving average for all losses and associated summaries for
    visualizing the performance of the network.

    Args:
    total_loss: Total loss from loss().
    Returns:
    loss_averages_op: op for generating moving averages of losses.
    """
    # Compute the moving average of all individual losses and the total loss.
    loss_averages = tf.train.ExponentialMovingAverage(0.9, name='avg')
    losses = tf.get_collection('losses')
    loss_averages_op = loss_averages.apply(losses + [total_loss])

    # Attach a scalar summary to all individual losses and the total loss; do the
    # same for the averaged version of the losses.
    for l in losses + [total_loss]:
        # Name each loss as '(raw)' and name the moving average version of the loss
        # as the original loss name.
        tf.summary.scalar(l.op.name + ' (raw)', l)
        tf.summary.scalar(l.op.name, loss_averages.average(l))

    return loss_averages_op

def train(total_loss, global_step, FLAGS):
    """Train the model.

    Create an optimizer and apply to all trainable variables. Add moving
    average for all trainable variables.

    Args:
    total_loss: Total loss from loss().
    global_step: Integer Variable counting the number of training steps
      processed.
    Returns:
    train_op: op for training.
    """
    # Variables that affect learning rate.
    num_batches_per_epoch = FLAGS.NUM_EXAMPLES_PER_EPOCH / FLAGS.batch_size
    decay_steps = int(num_batches_per_epoch * NUM_EPOCHS_PER_DECAY)

    # Decay the learning rate exponentially based on the number of steps.
    lr = tf.train.exponential_decay(INITIAL_LEARNING_RATE,
                                  global_step,
                                  decay_steps,
                                  LEARNING_RATE_DECAY_FACTOR,
                                  staircase=True)
    tf.summary.scalar('learning_rate', lr)

    # Generate moving averages of all losses and associated summaries.
    loss_averages_op = _add_loss_summaries(total_loss)

    # Compute gradients.
    with tf.control_dependencies([loss_averages_op]):
        opt = tf.train.GradientDescentOptimizer(lr)
        grads = opt.compute_gradients(total_loss)

    # Apply gradients.
    apply_gradient_op = opt.apply_gradients(grads, global_step=global_step)

    # Add histograms for trainable variables.
    for var in tf.trainable_variables():
        tf.summary.histogram(var.op.name, var)

    # Add histograms for gradients.
    for grad, var in grads:
        if grad is not None:
            tf.summary.histogram(var.op.name + '/gradients', grad)

    # Track the moving averages of all trainable variables.
    variable_averages = tf.train.ExponentialMovingAverage(
        MOVING_AVERAGE_DECAY, global_step)
    variables_averages_op = variable_averages.apply(tf.trainable_variables())

    with tf.control_dependencies([apply_gradient_op, variables_averages_op]):
        train_op = tf.no_op(name='train')

    return train_op



