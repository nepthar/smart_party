#!/usr/bin/env python3

import time
from enum import Enum

import sounddevice as sd
import numpy as np


class ELState(Enum):
  New = 1
  Setup = 2
  Running = 3
  Finished = 4


class Task:
  """ The basic unit of work for the event loop. """

  state = ELState.New

  def setup(self):
    """ Any setup that needs to run when a task is started. Called with
        the event loop that will be running it
    """
    pass

  def tick(self):
    """ The bit of work that this Task is responsible for in this frame.
        This task should return True if it wants to continue running or
        False if it's finished
    """
    raise NotImplementedError

  def finish(self):
    """ Anything that needs to run when a task is removed """
    pass

  def _setup(self, el):
    if self.state == ELState.New:
      self.el = el
      self.setup()
      self.state = ELState.Setup

  def _finish(self):
    if self.state in (ELState.Setup, ELState.Running):
      self.finish()
      self.state = ELState.Finished


class EventLoop:
  """ An event loop is responsible for running a collection of tasks at a
      given target FPS.

      In general, usage is as follows:

      loop = EventLoop(target_fps=10)

      key_press_check = KeyPoller('i')
      game_engine = GameEngine(key_press_check)

      loop.schedule(key_press_check)
      loop.schedule(game_engine)
      loop.run()
  """

  @staticmethod
  def _tick(task):
    """ Helper method to tick a task and call finish if it's done """
    if task.tick():
      return True
    else:
      task._finish()
      return False

  def __init__(self, target_fps=10, tasks=None):
    self.seconds_per_frame = 1.0 / float(target_fps)
    self.tasks = tasks if tasks else []
    self.state = ELState.New

  def run(self):
    """ Run this event loop forever """
    print(f"Running event loop @ {self.seconds_per_frame} seconds per frame")
    self.setup()
    frame_len_t = 0
    frame_start_t = 0
    self.state = ELState.Running

    try:
      while self.run:
        frame_start_t = time.time()
        self.tick()
        frame_len_t = time.time() - frame_start_t

        self.sleep_time = self.seconds_per_frame - frame_len_t
        if self.sleep_time > 0:
          time.sleep(self.sleep_time)

    except KeyboardInterrupt:
      print(" Quit.")

    finally:
      print(f"Ran for {self.frame} frames")
      self.finish()

  def setup(self):
    self.frame = 0
    self.sleep_time = 0.0
    self.long_frames = 0
    self.run = True

    [t._setup(self) for t in self.tasks]
    self.state = ELState.Setup

  def finish(self):
    [t._finish() for t in self.tasks]
    self.state = ELState.Finished

  def tick(self):
    self.tasks = [t for t in self.tasks if EventLoop._tick(t)]
    self.frame += 1

  def stop(self):
    self.run = False

  def schedule(self, task):
    """ Schedule an task to run in the event loop """
    if self.run:
      task._setup(self)
    self.tasks.append(task)

  def unschedule(self, task):
    """ Remove a task from the runnings manually """
    if self.run:
      task._finish()
    self.tasks.remove(task)


class Poller(Task):
  """ A poller is a task that always polls for & sets a value """

  def poll(self):
    raise NotImplementedError

  def tick(self):
    self.value = self.poll()
    return True


class MovingAverage(Poller):
  def __init__(self, underlying, window_size, default=0):
    self.p = underlying
    self.ws = window_size
    self.data = np.full(window_size, default)

  def poll(self):
    index = self.el.frame % window_size
    self.data[index] = self.p.poll()
    return self.fn()

