import numpy as np
from event_loop import *


class SoundLevelPoller(Poller):
  """ Poll for the absolute volume on the default microphone """
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


class SoundLevelPrinter(Task):
  """ Prints the sound level as measured by the level poller passed in
  """

  def __init__(self, levelPoller):
    self.poller = levelPoller

  def tick(self):
    bars = round(self.poller.value * 10)
    print('#' * bars)
    return True


class SystemLoadPrinter(Task):
  """ Records the "system load" or how long the event loop is working vs
      sleeping
  """

  def __init__(self, avg_len):
    self.avg_len = avg_len

  def setup(self):
    self.data = np.full(self.avg_len, self.el.seconds_per_frame)

  def tick(self):
    index = self.el.frame % self.avg_len
    self.data[index] = self.el.sleep_time

    if index == 0:
      avg_sleep = np.average(self.data)
      avg_load = (1.0 - avg_sleep / self.el.seconds_per_frame) * 100
      print(f"System Load: {round(avg_load, 2)}%")
    return True

