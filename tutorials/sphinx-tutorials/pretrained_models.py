"""
Using pretrained models
=======================
This tutorial explains how to use pretrained models in TorchRL.
"""
import tempfile

##############################################################################
# At the end of this tutorial, you will be capable of using pretrained models
# for efficient image representation, and fine-tune them.
#
# TorchRL provides pretrained models that are to be used either as transforms or as
# components of the policy. As the semantic is the same, they can be used interchangeably
# in one or the other context. In this tutorial, we will be using R3M (https://arxiv.org/abs/2203.12601),
# but other models (e.g. VIP) will work equally well.
#

# sphinx_gallery_start_ignore
import warnings

warnings.filterwarnings("ignore")
from torch import multiprocessing

# TorchRL prefers spawn method, that restricts creation of  ``~torchrl.envs.ParallelEnv`` inside
# `__main__` method call, but for the easy of reading the code switch to fork
# which is also a default spawn method in Google's Colaboratory
try:
    is_sphinx = __sphinx_build__
except NameError:
    is_sphinx = False

try:
    multiprocessing.set_start_method("spawn" if is_sphinx else "fork")
except RuntimeError:
    pass

# sphinx_gallery_end_ignore

import torch.cuda
from tensordict.nn import TensorDictSequential
from torch import nn
from torchrl.envs import Compose, R3MTransform, TransformedEnv
from torchrl.envs.libs.gym import GymEnv
from torchrl.modules import Actor

is_fork = multiprocessing.get_start_method() == "fork"
device = (
    torch.device(0)
    if torch.cuda.is_available() and not is_fork
    else torch.device("cpu")
)

##############################################################################
# Let us first create an environment. For the sake of simplicity, we will be using
# a common gym environment. In practice, this will work in more challenging, embodied
# AI contexts (e.g. have a look at our Habitat wrappers).
#
base_env = GymEnv("Ant-v4", from_pixels=True, device=device)

##############################################################################
# Let us fetch our pretrained model. We ask for the pretrained version of the model through the
# download=True flag. By default this is turned off.
# Next, we will append our transform to the environment. In practice, what will happen is that
# each batch of data collected will go through the transform and be mapped on a "r3m_vec" entry
# in the output tensordict. Our policy, consisting of a single layer MLP, will then read this vector and compute
# the corresponding action.
#
r3m = R3MTransform(
    "resnet50",
    in_keys=["pixels"],
    download=False,  # Turn to true for real-life testing
)
env_transformed = TransformedEnv(base_env, r3m)
net = nn.Sequential(
    nn.LazyLinear(128, device=device),
    nn.Tanh(),
    nn.Linear(128, base_env.action_spec.shape[-1], device=device),
)
policy = Actor(net, in_keys=["r3m_vec"])

##############################################################################
# Let's check the number of parameters of the policy:
#
print("number of params:", len(list(policy.parameters())))

##############################################################################
# We collect a rollout of 32 steps and print its output:
#
rollout = env_transformed.rollout(32, policy)
print("rollout with transform:", rollout)

##############################################################################
# For fine tuning, we integrate the transform in the policy after making the parameters
# trainable. In practice, it may be wiser to restrict this to a subset of the parameters (say the last layer
# of the MLP).
#
r3m.train()
policy = TensorDictSequential(r3m, policy)
print("number of params after r3m is integrated:", len(list(policy.parameters())))

##############################################################################
# Again, we collect a rollout with R3M. The structure of the output has changed slightly, as now
# the environment returns pixels (and not an embedding). The embedding "r3m_vec" is an intermediate
# result of our policy.
#
rollout = base_env.rollout(32, policy)
print("rollout, fine tuning:", rollout)

##############################################################################
# The easiness with which we have swapped the transform from the env to the policy
# is due to the fact that both behave like TensorDictModule: they have a set of `"in_keys"` and
# `"out_keys"` that make it easy to read and write output in different context.
#
# To conclude this tutorial, let's have a look at how we could use R3M to read
# images stored in a replay buffer (e.g. in an offline RL context). First, let's build our dataset:
#
from torchrl.data import LazyMemmapStorage, ReplayBuffer

buffer_scratch_dir = tempfile.TemporaryDirectory().name
storage = LazyMemmapStorage(1000, scratch_dir=buffer_scratch_dir)
rb = ReplayBuffer(storage=storage, transform=Compose(lambda td: td.to(device), r3m))

##############################################################################
# We can now collect the data (random rollouts for our purpose) and fill the replay
# buffer with it:
#
total = 0
while total < 1000:
    tensordict = base_env.rollout(1000)
    rb.extend(tensordict)
    total += tensordict.numel()

##############################################################################
# Let's check what our replay buffer storage looks like. It should not contain the "r3m_vec" entry
# since we haven't used it yet:
print("stored data:", storage._storage)

##############################################################################
# When sampling, the data will go through the R3M transform, giving us the processed data that we wanted.
# In this way, we can train an algorithm offline on a dataset made of images:
#
batch = rb.sample(32)
print("data after sampling:", batch)

# sphinx_gallery_start_ignore
# Remove scratch dir
try:
    import shutil

    # Use shutil.rmtree() to delete the directory and all its contents
    shutil.rmtree(buffer_scratch_dir)
    print(f"Directory '{buffer_scratch_dir}' deleted successfully.")
except FileNotFoundError:
    print(f"Directory '{buffer_scratch_dir}' not found.")
except Exception as e:
    print(f"Error deleting directory: {e}")
# sphinx_gallery_end_ignore
