
from pynput import keyboard

import hl2ss

host = '192.168.1.7'
port = hl2ss.IPCPort.VOICE_INPUT

strings = ['cat', 'dog', 'red', 'blue']


enable = True

def on_press(key):
    global enable
    enable = key != keyboard.Key.esc
    return enable

listener = keyboard.Listener(on_press=on_press)
listener.start()

client = hl2ss.ipc_vi(host, port)
client.open()

client.create_recognizer()
result = client.register_commands(True, strings)
print(result)
if (result):
    client.start()
    while (enable):
        events = client.pop()
        for event in events:
            event.unpack()
            print(f'event: {event.index} {event.confidence} {event.phrase_duration} {event.phrase_start_time} {event.raw_confidence}')

    client.stop()
    client.clear()

client.close()

listener.join()
