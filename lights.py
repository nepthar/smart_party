#!/usr/bin/env python3

import socket
import time
import select
import json
from enum import Enum

import sounddevice as sd
import numpy as np

GlobalSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
GloablSoundLevel = 0


def enc(ascii_string):
  key = 0xAB
  bs = bytearray(ascii_string, 'ascii')
  for i, byte in enumerate(bs):
    key = key ^ byte
    bs[i] = key
  return bytes(bs)


def dec(byte_string):
  key = 0xAB
  bs = bytearray(byte_string)
  for i, byte in enumerate(bs):
    bs[i] = key ^ byte
    key = byte
  return bs.decode('ascii')


class Bulb:

  SYS_CMD = '{"system":{"get_sysinfo":{}}}'

  @staticmethod
  def trans_cmd_str(cmd):
    """ Make a transition command string from the command """
    return ''.join((
      '{"smartlife.iot.smartbulb.lightingservice":{',
      '"transition_light_state":', json.dumps(cmd), '}}'
    ))

  @staticmethod
  def all(timeout=1):
    """ Find all of the lightbulbs on your network. Most respond in
        less than 0.1 seconds
    """
    msg = enc(Bulb.SYS_CMD)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(msg, ('255.255.255.255', 9999))

    lights = []
    try:
      while True:
        s.settimeout(timeout)
        data, addr = s.recvfrom(1024)
        lights.append(Bulb(addr, sysinfo=dec(data)))

    except socket.timeout:
      pass

    return lights

  def __init__(self, ip_port, sysinfo=None, sock=GlobalSocket):
    self.addr = ip_port
    self.sock = sock
    self.transition_period_ms = 0
    self.name = 'unknown'

    if sysinfo:
      self._read_sysinfo(sysinfo)
    else:
      self.refresh()

  def _read_sysinfo(self, sysinfo):
    js = json.loads(sysinfo)['system']['get_sysinfo']

    self.name = js['alias']
    self.power = js['light_state']['on_off'] == 1
    state = js['light_state'] if self.power else js['preferred_state'][0]
    self.state = state

  def write_state(self, transition_ms=0):
    d = {}
    if self.power:
      d['on_off'] = 1
      d['hue'] = self.hue
      d['saturation'] = self.sat
      d['color_temp'] = self.temp
      d['brightness'] = self.bright
      d['transition_period'] = transition_ms
    else:
      d['on_off'] = 0

    return self.cmd(Bulb.trans_cmd_str(d))

  def hue(self, hue):
    hue_cmd = Bulb.trans_cmd_str({'hue': hue})
    return self.cmd(hue_cmd)

  def onoff(self):
    self.power = not self.power
    value = 1 if self.power else 0
    return self.cmd(Bulb.trans_cmd_str({'on_off': value}))

  def off(self):
    if self.power:
      self.power = False
      return self.cmd(Bulb.trans_cmd_str({'on_off': 0}))

  def cmd(self, cmd_string):
    e = enc(cmd_string)
    self.sock.sendto(e, self.addr)
    data, addr = self.sock.recvfrom(1024)
    return dec(data)

  def refresh(self):
    self._read_sysinfo(self.cmd(Bulb.SYS_CMD))

  def __str__(self):
    return f"Bulb \"{self.name}\" @ {self.addr[0]}"

  def __repr__(self):
    return f"<{self.__str__()}>"


class ELState(Enum):
  New = 1
  Setup = 2
  Running = 3
  Finished = 5


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

  def run(self):
    """ Run this event loop forever """
    print(f"Running event loop @ {self.seconds_per_frame} seconds per frame")
    self.setup()
    frame_len_t = 0
    frame_start_t = 0

    try:
      while self.run:
        frame_start_t = time.time()
        self.tick()
        frame_len_t = time.time() - frame_start_t

        self.sleep_time = self.seconds_per_frame - frame_len_t
        if self.sleep_time > 0:
          time.sleep(self.sleep_time)

    finally:
      self.finish()

  def setup(self):
    self.frame = 0
    self.sleep_time = 0.0
    self.long_frames = 0
    self.run = True

    [t._setup(self) for t in self.tasks]
    self.status = EventLoop.SETUP

  def finish(self):
    [t._finish() for t in self.tasks]
    self.status = EventLoop.FINISHED

  def tick(self):
    self.tasks = [t for t in self.tasks if EventLoop._tick(t)]
    self.frame += 1

  def stop(self):
    self.run = False

  def schedule(self, task):
    """ Schedule an task to run in the event loop """
    if self.status == EventLoop.RUNNING:
      task.setup(self)
    self.tasks.append(task)

  def unschedule(self, task):
    """ Remove a task from the runnings manually """
    if self.status == EventLoop.RUNNING:
      task.finish()
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

class SoundLevelPoller(Poller):
  """ Poll for the absolute volume on the default microphone """
  def __init__(self):
    self.avail = 0

  def setup(self):
    self.stream = sd.InputStream(samplerate=12000, blocksize=1)
    self.stream.start()

  def poll(self):
    self.avail = self.stream.read_available
    if self.avail:
      data, overflowed = self.stream.read(self.avail)
      return np.linalg.norm(data)
    else:
      return 0.0

  def finish(self):
    self.stream.stop()
    self.stream.close()


class SoundLevelPrinter(Poller):
  """ Prints the sound level as measured by the level poller passed in
  """

  def __init__(self, levelPoller):
    self.poller = levelPoller

  def tick(self):
    print(round(self.poller.level * 1000))


class SystemLoadPrinter(Poller):
  """ Records the "system load" or how long the event loop is working vs
      sleeping
  """

  def __init__(self, avg_len):
    self.avg_len = avg_len
    self.data = [0] * avg_len

  def setup(self, el):
    self.el = el

  def tick(self):
    index = self.el.frame % self.avg_len
    self.data[index] = self.el.sleep_time

    if index == 0:
      avg_sleep = sum(self.data) / float(self.avg_len)
      avg_load = (1.0 - avg_sleep / self.el.seconds_per_frame) * 100
      print(f"System Load: {round(avg_load, 2)}%")


el = EventLoop(1000) # ten FPS event loop
soundPoller = SoundLevelPoller()

el.schedule(soundPoller)
el.schedule(SoundLevelPrinter(soundPoller))
el.schedule(SystemLoadPrinter(2000))

el.run()
