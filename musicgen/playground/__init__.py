"""M12 playground — a FastAPI live-control service around one MusicEngine +
RealtimeSynthPlayer (PLANS.md §11, M12).

Audio is fully local: the browser is a control-and-visualization surface that
speaks a small WebSocket/JSON protocol to this service, which drives the
existing realtime synth player on the machine's own device. Nothing here is on
the generation core's import path — it lives behind the ``[playground]`` extra,
the same boundary discipline as ``midi_io`` (mido) and ``synth`` (signalflow).
"""
