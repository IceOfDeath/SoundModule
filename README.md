# SoundModule

Simple open sourced sound player for Matcha

## Quick Start

Build and start `Matchasoundmodule.exe` first. When the local server is ready, load the client:

```lua
local SM = loadstring(game:HttpGet("https://raw.githubusercontent.com/IceOfDeath/SoundModule/refs/heads/main/Client.lua"))() or SM
```

## API

| Function | Description |
| --- | --- |
| `SM:Status()` | Returns the local server connection status. |
| `SM:IsAudio(audioname: string)` | Checks whether audio with the supplied name is available. |
| `SM:DelAudio(audioname: string)` | Deletes the saved and cached audio with the supplied name. |
| `SM:GetAudio(link: string, audioname: string)` | Downloads audio from a direct/raw URL and saves it with the supplied name. |
| `SM:PlayAudio(audioname: string)` | Plays previously downloaded audio with the supplied name. |

`audioname` is always specified **without** an extension. The service accepts WAV, MP3, and OGG sources, then stores the result as `audioname.wav` in `C:/Matcha/workspace/soundmodule`.

## System Tray Settings

`Matchasoundmodule.exe` runs without a visible main window. Its icon appears in the Windows system tray.

- **Connected / Disconnected** — shows whether the Luau client has called `/Status` recently. The tray icon is green while connected and red while disconnected.
- **Maximum audio size** — limits the source-file size accepted by downloads: 1 MB to 128 MB.
- **Maximum cache size** — limits in-memory audio cache usage: 256 MB to 4 GB. The oldest cached audio is removed first when space is needed.
- **Sound Player** — enables or disables local playback while keeping download and cache support available.
- **AutoStartup** — starts the application when the current Windows user signs in.
- **Exit** — stops the local server and closes the application.

## Examples

### Check whether the service is available

```lua
local state = SM:Status()

if state then
	print("Audio module working!")
else
	error("Audio module not working")
end
```

### Download audio when it is not already available

```lua
local hitsound = SM:IsAudio("beep")

if hitsound then
	SM:PlayAudio("beep")
else
	SM:GetAudio("https://github.com/IceOfDeath/SoundModule/raw/refs/heads/main/beep.wav", "beep")
	SM:PlayAudio("beep")
end
```

### Replace an existing audio file

```lua
local BeepOld = SM:IsAudio("beep")

if BeepOld then
	SM:DelAudio("beep")
	SM:GetAudio("https://github.com/IceOfDeath/SoundModule/raw/refs/heads/main/beep.wav", "beep")
else
	SM:GetAudio("https://github.com/IceOfDeath/SoundModule/raw/refs/heads/main/beep.wav", "beep")
end
```
