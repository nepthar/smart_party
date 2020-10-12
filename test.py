#!/usr/bin/env python3


from event_loop import *
from tasks import *

el = EventLoop(30) # ten FPS event loop
soundPoller = SoundLevelPoller()

el.schedule(soundPoller)
el.schedule(SoundLevelPrinter(soundPoller))
el.schedule(SystemLoadPrinter(100))

el.run()
