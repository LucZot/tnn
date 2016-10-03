"""
Main run module
"""

from __future__ import absolute_import, division, print_function

import json

import numpy as np
import tensorflow as tf

from tfutils import base, data
import model


def get_data(train=True,
             batch_size=256,
             data_path='',
             image_size_crop=224,
             num_train_images=2**20,
             num_valid_images=2**14,
             num_threads=4,
             random_crop=True
             ):
    # Get images and labels for ImageNet.
    print('images and labels done')
    if train:
        subslice = range(num_train_images)
    else:
        subslice = range(num_train_images, num_train_images + num_valid_images)

    with tf.device("/gpu:0"):
        d = data.ImageNet(data_path,
                          subslice,
                          crop_size=image_size_crop,
                          batch_size=batch_size,
                          n_threads=num_threads)

    return d


def get_learning_rate(num_batches_per_epoch=1,
                      learning_rate_base=.01,
                      learning_rate_decay_factor=.95,
                      num_epochs_per_decay=1
                      ):
    # Decay the learning rate exponentially based on the number of steps.
    if learning_rate_decay_factor is None:
        learning_rate = learning_rate_base  # just a constant.
    else:
        # Calculate the learning rate schedule.
        global_step = [v for v in tf.all_variables() if v.name == 'global_step:0'][0]
        learning_rate = tf.train.exponential_decay(
            learning_rate_base,  # Base learning rate.
            global_step,  # Current index into the dataset.
            num_batches_per_epoch * num_epochs_per_decay,  # Decay step (aka once every EPOCH)
            learning_rate_decay_factor,  # Decay rate.
            staircase=True)

    return learning_rate


def get_optimizer(loss, learning_rate=.01, momentum=.9, grad_clip=True):
    # Create optimizer for gradient descent.
    optimizer = tf.train.MomentumOptimizer(learning_rate=learning_rate,
                                           momentum=momentum)
    # optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)
    gvs = optimizer.compute_gradients(loss)
    global_step = [v for v in tf.all_variables() if v.name == 'global_step:0'][0]
    if grad_clip:
        capped_gvs = [(tf.clip_by_value(grad, -1., 1.), var)
                      for grad, var in gvs if grad is not None]
        # gradient clipping. Some gradients returned are 'None' because
        # no relation between the variable and tot loss; so we skip those.
        optimizer = optimizer.apply_gradients(capped_gvs,
                                              global_step=global_step)
        print('Gradients clipped')
    else:
        optimizer = optimizer.apply_gradients(gvs, global_step=global_step)
        print('Gradients not clipped')

    return optimizer


def main(args):
    params = json.load(open('params.json'))
    # dict keys are stored as str; coverting back to int
    for k, v in params['model']['layer_sizes'].items():
        params['model']['layer_sizes'][int(k)] = v
        del params['model']['layer_sizes'][k]

    with tf.Graph().as_default():  # to have multiple graphs [ex: eval, train]
        rng = np.random.RandomState(seed=params['seed'])
        tf.set_random_seed(params['seed'])

        tf.get_variable('global_step', [],
                        initializer=tf.constant_initializer(0),
                        trainable=False)

        train_data = get_data(train=True, **params['data'])

        input_seq = [train_data.batch['data']] * params['model']['T_tot']
        label_seq = [train_data.batch['labels']] * params['model']['T_tot']
        output_seq = model.get_model(model.alexnet, input_seq,
                                     train=params['train'],
                                     features_layer=None,  # last layer
                                     **params['model']
                                     )

        loss = model.get_loss(output_seq, label_seq, loss_fun=None, **params['loss'])
        lr = get_learning_rate(params['num_train_batches'], **params['learning_rate'])
        optimizer = get_optimizer(loss, lr, **params['optimizer'])

        # validation
        valid_data = get_data(train=False, **params['data'])
        top_1_ops = [tf.nn.in_top_k(output, valid_data.batch['labels'], 1)
                     for output in output_seq]
        top_5_ops = [tf.nn.in_top_k(output, valid_data.batch['labels'], 5)
                     for output in output_seq]

        # create session
        sess = tf.Session(config=tf.ConfigProto(
                          allow_soft_placement=True,
                          log_device_placement=params['log_device_placement']))

        saver = base.Saver(sess, **params['saver'])

        # to keep consistent count (of epochs passed, etc.)
        start_step = params['saver']['start_step'] if params['saver']['restore_vars'] else 0
        end_step = params['num_epochs'] * params['num_train_batches']

        base.run(sess,
                 [train_data, valid_data],
                 saver,
                 train_targets={'loss': loss, 'lr': lr, 'opt': optimizer},
                 valid_targets={'top1': top_1_ops, 'top5': top_5_ops},
                 start_step=start_step,
                 end_step=end_step)


if __name__ == '__main__':
    tf.app.run()