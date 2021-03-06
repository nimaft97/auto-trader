# -*- coding: utf-8 -*-
"""Project B.Sc.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1Xjpz_pcLkQpa_c_NClSvKZZk8Hzgp_pz
"""

# Commented out IPython magic to ensure Python compatibility.
# %tensorflow_version 1.x

from keras.models import Sequential
from keras.layers import Dense
from keras.optimizers import Adam
from keras.losses import MSE

from collections import deque
import random
import numpy as np
from numpy.fft import fft, ifft

import gym
from gym import spaces
from gym.utils import seeding

import itertools

import os
import pandas as pd

from sklearn.preprocessing import StandardScaler, MinMaxScaler
from sklearn.model_selection import TimeSeriesSplit

import pickle
import time
from time import strftime

import re

import matplotlib.pyplot as plt

def mlp(n_obs, n_action, n_hidden_layer=1, n_neuron_per_layer=32,
        activation='relu', loss='mse'): ## n_obs= state_size
  """ A multi-layer perceptron """
  model = Sequential()
  model.add(Dense(n_neuron_per_layer, input_dim=n_obs[0], activation=activation))
  for _ in range(n_hidden_layer):
    model.add(Dense(n_neuron_per_layer, activation=activation))
  model.add(Dense(n_action, activation='linear'))
  model.compile(loss=loss, optimizer=Adam())
  print(model.summary())
  return model

class DQNAgent(object):
  """ A simple Deep Q agent """
  def __init__(self, state_size, action_size):
    self.state_size = state_size
    self.action_size = action_size
    self.memory = deque(maxlen=2000)
    self.gamma = 0.95  # discount rate
    self.epsilon = 1.0  # exploration rate
    self.epsilon_min = 0.01
    self.epsilon_decay = 0.995
    self.model = mlp(state_size, action_size)


  def remember(self, state, action, reward, next_state, done):
    self.memory.append((state, action, reward, next_state, done))


  def act(self, state):
    if np.random.rand() <= self.epsilon: ## considering a chance for having random actions
      return random.randrange(self.action_size)
    act_values = self.model.predict(state)
    return np.argmax(act_values[0])  # returns action


  def replay(self, batch_size=32):
    minibatch = random.sample(self.memory, batch_size)
    states = np.array([tup[0][0] for tup in minibatch])
    actions = np.array([tup[1] for tup in minibatch])
    rewards = np.array([tup[2] for tup in minibatch])
    next_states = np.array([tup[3][0] for tup in minibatch])
    done = np.array([tup[4] for tup in minibatch])
    # print(f"states={states}") ##my_print

    # Q(s', a)
    target = rewards + self.gamma * np.amax(self.model.predict(next_states), axis=1)
    # end state target is reward itself (no lookahead)
    target[done] = rewards[done] ##there is no next_step anymore

    # Q(s, a)
    target_f = self.model.predict(states)
    # make the agent to approximately map the current state to future discounted reward
    target_f[range(batch_size), actions] = target
    # print(f"target_f.shape:{target_f.shape}\ntarget_f:{target_f}")

    self.model.fit(states, target_f, epochs=1, verbose=0, validation_split=0)

    if (self.epsilon > self.epsilon_min):
      self.epsilon *= self.epsilon_decay ## to lower the probability of following a random action


  def load(self, name):
    self.model.load_weights(name)


  def save(self, name):
    self.model.save_weights(name)

class TradingEnv(gym.Env): ## gym.Env is a Super Class
  def __init__(self, train_data, init_invest=20000):
    # data
    self.stock_price_history = np.around(train_data) # round up to integer to reduce state space
    self.n_stock, self.n_step = self.stock_price_history.shape
    # instance attributes
    self.init_invest = init_invest
    self.cur_step = None 
    self.stock_owned = None 
    self.stock_price = None
    self.cash_in_hand = None
    self.indicator_20std=None ##extra_indicator
    # action space
    self.action_space = spaces.Discrete(3**self.n_stock) ##n stocks available and 3 actions possible for each
    # observation space: give estimates in order to sample and build scaler
    stock_max_price = self.stock_price_history.max(axis=1) 
    stock_range = [[init_invest * 2 // mx] for mx in stock_max_price]
    price_range = [[mx] for mx in stock_max_price]
    cash_in_hand_range = [[init_invest * 2]]
    """ 1. stocks owned, 2. stocks' prices, 3. stocks' std, 4. cash in hand """
    self.observation_space = spaces.MultiDiscrete(stock_range + price_range + price_range + cash_in_hand_range)
    # seed and start
    self._seed()
    self._reset()


  def _seed(self, seed=None):
    self.np_random, seed = seeding.np_random(seed)
    return [seed]


  def _reset(self):
    self.cur_step = 0
    self.stock_owned = [0] * self.n_stock
    self.stock_price = self.stock_price_history[:, self.cur_step]
    # self.indicator_mean, self.indicator_12ewma, self.indicator_26ewma, self.indicator_fourier_real, self.indicator_fourier_imaginary = self._indicators_reset() ##my_indicator
    self.indicator_20std=self._indicators_reset()
    self.cash_in_hand = self.init_invest
    return self._get_obs()

  def _indicators_reset(self):
    self.indicator_20std=np.zeros((self.n_stock, 1))
    # self.indicator_mean=self.stock_price_history[:, self.cur_step]
    # self.indicator_12ewma=self.stock_price_history[:, self.cur_step]
    # self.indicator_26ewma=self.stock_price_history[:, self.cur_step]
    # self.indicator_fourier_real=self.stock_price_history[:, self.cur_step]
    # self.indicator_fourier_imaginary=np.zeros(self.indicator_fourier_real.shape)
    # return self.indicator_mean, self.indicator_12ewma, self.indicator_26ewma, self.indicator_fourier_real, self.indicator_fourier_imaginary
    return self.indicator_20std


  def _step(self, action):
    assert self.action_space.contains(action)
    prev_val = self._get_val()
    self.cur_step += 1
    self.stock_price = self.stock_price_history[:, self.cur_step] # update price
    self.indicator_20std=self._indicators_step()
    self._trade(action)
    cur_val = self._get_val()
    reward = cur_val - prev_val
    done = self.cur_step == self.n_step - 1
    info = {'cur_val': cur_val}
    return self._get_obs(), reward, done, info

  def _indicators_step(self): ##extra_indicator
    self.indicator_20std=np.std(self.stock_price_history[:, -min(20, self.cur_step+1):], axis=1) #std for at most 20 last records for each stock
    # self.indicator_mean=self.stock_price_history[:, 0:self.cur_step+1].mean(axis=1)
    # temp_df=pd.DataFrame(self.stock_price_history[:, 0:self.cur_step+1])
    # # self.indicator_12ewma=temp_df.ewm(span=12, axis=1).mean().iloc[:, self.cur_step]
    # # self.indicator_26ewma=temp_df.ewm(span=26, axis=1).mean().iloc[:, self.cur_step]
    # self.indicator_12ewma=np.array(temp_df.ewm(span=12, axis=1).mean())[:, self.cur_step]
    # self.indicator_26ewma=np.array(temp_df.ewm(span=26, axis=1).mean())[:, self.cur_step]
    # ##fourier transform with 50 comkponents
    # fft_list=fft(np.array(temp_df))
    # fft_list[50:-50]=0
    # indicator_fourier=ifft(fft_list)[:, self.cur_step]
    # self.indicator_fourier_real, self.indicator_fourier_imaginary=np.real(indicator_fourier), np.imag(indicator_fourier)
    # #--------------
    # return self.indicator_mean, self.indicator_12ewma, self.indicator_26ewma, self.indicator_fourier_real, self.indicator_fourier_imaginary
    # return self.indicator_20std, self.indicator_volmorethanavg
    return self.indicator_20std

  def _get_obs(self):
    obs = []
    obs.extend(self.stock_owned)
    obs.extend(self.stock_price) 
    # obs.extend(self.indicator_mean)##extra_indicator
    # obs.extend(self.indicator_12ewma)##extra_indicator
    # obs.extend(self.indicator_26ewma)##extra_indicator
    # obs.extend(self.indicator_fourier_real)##extra_indicator
    # obs.extend(self.indicator_fourier_imaginary)##extra_indicator
    obs.extend(self.indicator_20std)##extra_indicator
    obs.append(self.cash_in_hand)
    return obs


  def _get_val(self): ##returns the total value owned: stock plus cash
    return np.sum(self.stock_owned * self.stock_price) + self.cash_in_hand


  def _trade(self, action):
    # all combo to sell(0), hold(1), or buy(2) stocks
    action_combo = list(map(list, itertools.product([0, 1, 2], repeat=self.n_stock)))
    action_vec = action_combo[action]

    # one pass to get sell/buy index
    sell_index = []
    buy_index = []
    for i, a in enumerate(action_vec):
      if (a == 0):
        sell_index.append(i)
      elif (a == 2):
        buy_index.append(i)

    # two passes: sell first, then buy; might be naive in real-world settings
    if (sell_index):
      for i in sell_index:
        self.cash_in_hand += self.stock_price[i] * self.stock_owned[i]
        self.stock_owned[i] = 0
    if (buy_index):##buys the stock one by one
      can_buy = True
      while (can_buy):
        for i in buy_index: ##it's better to use % instead of decreasing one by one
          if self.cash_in_hand >= self.stock_price[i]: ##I made it >= instead of >
            self.stock_owned[i] += 1 # buy one share
            self.cash_in_hand -= self.stock_price[i]
          else:
            can_buy = False

def get_data(col='Close'):
  """ Returns a 3 x n_step array """
  msft=pd.read_csv('/content/drive/My Drive/colab files/stocks/MSFT.csv', usecols=[col])
  ibm=pd.read_csv('/content/drive/My Drive/colab files/stocks/IBM.csv', usecols=[col])
  qcom=pd.read_csv('/content/drive/My Drive/colab files/stocks/QCOM.csv', usecols=[col])
  
  return np.array([msft[col].values[::-1],
                   ibm[col].values[::-1],
                   qcom[col].values[::-1]])

def get_scaler(env, state_size):
  """ Takes an env and state size -> returns a scaler for its observation space """
  low = [0] * (state_size)

  high = []
  max_price = env.stock_price_history.max(axis=1)
  min_price = env.stock_price_history.min(axis=1)
  max_cash = env.init_invest * 3 # 3 is a magic number...
  max_stock_owned = max_cash // min_price
  for i in max_stock_owned:
    high.append(i)
  for i in max_price: ## for price
    high.append(i)
  for i in max_price: ##extra_indicator for 20std
    high.append(i)
  high.append(max_cash)

  scaler = StandardScaler() 
  scaler.fit([low, high])
  return scaler


def maybe_make_dir(directory):
  if not os.path.exists(directory):
    os.makedirs(directory)

maybe_make_dir('weights')
maybe_make_dir('portfolio_val')
data = np.around(get_data())

def plot_curves(portfolio_value, initial_invest, cur_round):
  n=len(portfolio_value)
  portfolio_value_mean=np.array(portfolio_value).mean()
  plt.plot(np.arange(n), portfolio_value, label=f"round {cur_round} = {portfolio_value_mean}")
  plt.plot(np.arange(n), np.ones(n)*initial_invest, 'r--')
  # plt.plot(np.arange(n), np.ones(n)*portfolio_value_mean, label='')
  plt.xlabel('epoch')
  plt.ylabel('end value')
  plt.legend()
  plt.plot()

mode='train'
episode=50
batch_size=32
initial_invest=20000
cont=input(r"Have you run this model before? [y/n]: ")
if (cont=='n'):
  env = TradingEnv(data, initial_invest)
  state_size = env.observation_space.shape
  action_size = env.action_space.n
  agent = DQNAgent(state_size, action_size)

  ans=input("Do you want to load any other model? [y/n]: ")
  if(ans=='y'):
    init_weight='weights/'
    init_weight+=input("Please enter the file's name containing initializing weights with .h5 format: ")
    agent.load(init_weight)

n_splits=3
kf=TimeSeriesSplit(n_splits=n_splits)
for i, (train_index, test_index) in enumerate(kf.split(data[0])):
  print(f"round: {i+1}")
  train_data, test_data=data[:, train_index], data[:, test_index]
  env=TradingEnv(train_data, init_invest=initial_invest)
  scaler = get_scaler(env, state_size[0])
  portfolio_value = []
  timestamp = strftime(f'round {i+1}-%Y%m%d%H%M')
  for e in range(episode):
    state = env._reset()
    # print(f"\nepisode={e+1}\tstate:::{state}\n")
    state = scaler.transform([state])
    for time in range(env.n_step):
      # print(f"state:::{state}")
      action = agent.act(state)
      next_state, reward, done, info = env._step(action)
      # print(f"\nepoch={time+1}\tnext_state:::{next_state}\ncurrent_value={info['cur_val']}")
      next_state = scaler.transform([next_state])
      if (mode == 'train'):
        agent.remember(state, action, reward, next_state, done)
      state = next_state
      if (done):
        print(f"episode: {e+1}/{episode}, episode end value: {info['cur_val']}")
        # print("episode: {}/{}, episode end value: {}".format(
        #   e + 1, episode, info['cur_val']))
        portfolio_value.append(info['cur_val']) # append episode end portfolio value
        break
      if (mode == 'train' and len(agent.memory) > batch_size):
        # print(f"agent.replay -> batch_size={batch_size}")
        agent.replay(batch_size)
    if (mode == 'train' and (e+1) % 10 == 0):  # checkpoint weights
      weights='weights/{0}-{1}-dqn.h5'.format(timestamp, e+1)
      agent.save(weights)
  # save portfolio value history to disk
  with open(f'portfolio_val/{timestamp}-{mode}.csv', 'w') as fp:
    p_value=pd.Series(portfolio_value)
    p_value.to_csv(fp, index=False, header=True)
  plot_curves(portfolio_value, initial_invest, cur_round=i+1)

