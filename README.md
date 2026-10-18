# Trials Frontier **Original** Local Server Project

## Language:
**English** | [简体中文](README_CN.md)

## Project Overview
**This project was initially put on hold indefinitely due to a lack of technical expertise. After AI-assisted reverse engineering, the old version (unreleased) was reorganized and the code was written.**  
The reason for creating this project is simple: the game was shut down. Without the server, the online mode and some specific features are unavailable.  
The server can currently run directly on Windows 10/11. The client is limited to Android devices.
  
## Project Goals
1. Become fully open source, with transparent and reviewable data (however, save data remains in the hands of the person hosting the server locally)
2. Do not connect to Ubisoft services or depend on Ubisoft accounts
3. Support local multiplayer and, optionally, multiplayer over a wide-area network through local tunneling
4. Provide a minimal playable server
5. Support account registration and save-data management
6. Support Midnight Circuit, Bunker, and leaderboards
  
## Documentation and Server Features
- [Server operations guide](server/OPERATIONS.md): newcomer instructions for Midnight Circuit and Bunker/PvP, including rewards, track selection, start/end windows, backups, rollback, and troubleshooting.
- The embedded admin panel is available at `http://127.0.0.1:8123/__ui`; local endpoint help is at `http://127.0.0.1:8123/__help`.
- The server stores accounts, saves, match state, and logs locally under `server/data`. Keep the admin port on a trusted LAN and back up data before changing live configuration.
- Server responses and client display are separate contracts. A successful local HTTP response does not by itself prove that an Android client will show a map, banner, or entry point.

## Run from Source
The server has no third-party Python dependencies and requires Python 3.8 or newer:

```powershell
python server/tf_server.py --host 0.0.0.0 --port 8123
```

Then open the admin panel, register a game account, and point the Android client's `tf_server.txt` at the computer's LAN address and port. Stop the process with `Ctrl+C` when finished.

## Important Notes  
Since this does not involve official servers, there is no official leaderboard data. This means your existing data cannot be carried over, and you will not be able to see information regarding other players from the official servers.  
If you play with other players on a local server, their track records can be uploaded to the server and displayed.  
PvP Matchmaking Mechanism:  
If there are players online on the server (at least two players required) and both parties initiate matchmaking within one minute, they will be matched against each other. Otherwise, you will be matched with a **Ghost Rider** — an AI-controlled opponent.  
  
## Privacy and Legal Notice
1. This project does not collect any data unless you submit a log to report a bug.  
2. This project is non-profit, will never charge any fees, and will not request sponsorship.  
3. This project is intended for communication and educational purposes only.  

## Installation and How to Play
1. Download the server (`TrialsFrontierServer_vx.x.exe`) and client (`Trials_Frintier_Local_server_patched.apk`) from [Releases](https://github.com/Coconutat/Trials_Frontier_Offline_Hack_Server/releases).  
2. Install `Trials_Frintier_Local_server_patched.apk`.  
3. Place `TrialsFrontierServer_vx.x.exe` in a separate folder you can easily find, then double-click it to open it. This will open a console and a browser page. The console will output an admin username and password; enter them on the web page to access the admin panel. You can change the admin password after logging in.  
4. Register a game account as instructed in the admin panel.  
5. On your Android phone, open `/sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/`, find `tf_server.txt`, and enter the IP address and port shown in the web admin panel on your computer.  
6. Open the game and log in with the account you registered.

***
## Additional Notice
This project is not affiliated with the [Trials Frontier Revival Project](https://trialsproject.com/) in any way. The [Trials Frontier Revival Project](https://trialsproject.com/) is owned by AurisTFG and Somnic.  
The [Trials Frontier Revival Project](https://trialsproject.com/) provides a richer and more modern gaming experience.  
If you’re looking for a richer gaming experience, I recommend giving their version a try.  
***

## The future of the project? Or, can I help with this project?  
Regarding the **future of the project**:  
To be honest, I’m not sure. This project was created by me, with the assistance of AI. I have already implemented the vast majority of the essential features. Given that the superior [Trials Frontier Revival Project](https://trialsproject.com/) has already been released to the public, the only remaining advantage of this project is that it is open-source.  
Regarding **whether you can help**:  
Of course you can! I would be very happy to have players or developers who love **Trials Frontier** contribute to making this project even better.  
Regardless of whether you are interested in this project or not, thank you for reading this far.  
  
## Open-Source License
GPL-v3 Only: [LICENSE](LICENSE)
