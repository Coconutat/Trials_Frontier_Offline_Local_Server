# 特技摩托前线**原版**本地服务器项目  

## 语言:
[English](README.md) | **简体中文**

## 项目概述
**本项目起初因为技术力不足无限搁置，经AI逆向研究，后重新整理旧版本(未公布)，编写代码。**  
创建项目原因很简单，游戏停服了。没有服务器就无法游玩在线模式，和一些特定功能。  
目前服务端可以在Windows 10/11直接运行。客户端仅限安卓设备使用。
  
## 项目目标
1. 完全开源，数据透明可审查(但是存档保留在本地开服者手中)
2. 不连接Ubisoft服务，不依赖Ubisoft账户
3. 本地联机或者可以本地穿透广域联机
4. 最小化可玩服务器
5. 账户注册，存档管理
6. 游玩午夜杯，碉堡，排行榜。

## 文档与服务端功能
- [服务端运营手册](server/OPERATIONS.md)：面向新手说明午夜杯、碉堡/PVP 的奖励、赛道选择、开始/结束窗口、备份、撤销和排障。
- 内置管理后台地址：`http://127.0.0.1:8123/__ui`；本地端点帮助：`http://127.0.0.1:8123/__help`。
- 账户、存档、对局状态和日志都保存在 `server/data`。请只在可信局域网开放管理端口，修改运行配置前先备份。
- 服务端响应和客户端显示是两个独立契约。HTTP 成功不等于 Android 客户端一定会显示地图、横幅或入口。

## 从源码启动
服务端不依赖第三方 Python 包，需要 Python 3.8 或更高版本：

```powershell
python server/tf_server.py --host 0.0.0.0 --port 8123
```

然后打开管理后台，注册游戏账号，并把安卓客户端的 `tf_server.txt` 指向电脑的局域网地址和端口。使用 `Ctrl+C` 停止服务。

## 注意  
由于不涉及官方服务器，所以没有官方服务器的排行榜数据。这意味着你原来的数据无法直接被继承，你也看不到以前各个玩家的信息。  
如果你和几个本地服务器玩家玩，他们的赛道记录是可以上传到服务器并且显示的。  
碉堡PVP匹配机制:  
当服务器有玩家在线(至少要有两名玩家)，且在一分钟内双方按下匹配则可以互相匹配上。否则会匹配到**幽灵车手**，一个AI人机。  
  
## 隐私及法律声明
1. 本项目不会收集任何数据，除非项目拥有bug而你提交log。  
2. 本项目非盈利，且永远不会收取任何费用，也不会要求赞助。 
3. 项目仅供交流学习。  

## 如何安装游玩
1. 在[Releases](https://github.com/Coconutat/Trials_Frontier_Offline_Hack_Server/releases)内下载服务端（TrialsFrontierServer_vx.x.exe）和客户端（Trials_Frintier_Local_server_patched.apk）。  
2. 安装Trials_Frintier_Local_server_patched.apk 
3. 把TrialsFrontierServer_vx.x.exe放在一个单独你找得到的文件夹，然后双击打开。这是会打开一个控制台和浏览器页面。控制台会输出一个admin账号和密码，在网页输入账号和密码进入控制后台。进入后就可以更改admin账号的密码了。  
4. 根据后台提示注册一个游戏账号。  
5. 在安卓手机的/sdcard/Android/data/com.ubisoft.redlynx.trialsfrontier.ggp/files/路径，找到tf_server.txt，在这里填写你电脑网页后台看到的ip和端口号。  
6. 打开游戏，登陆你刚注册的账号即可。

***
## 额外声明:
本项目和[Trials Frontier Revival Project](https://trialsproject.com/)项目无任何关系，[Trials Frontier Revival Project](https://trialsproject.com/)由 AurisTFG & Somnic 大佬拥有。  
[Trials Frontier Revival Project](https://trialsproject.com/)提供更加丰富，更加现代的游戏体验。  
如果你想体验更加丰富的游戏体验，我推荐你去尝试他们的版本。    
***

## 项目未来？ 或者 我是否可以帮助这个项目  
关于 **项目未来** :  
老实说，我不知道。这个项目是我个人和AI一起完成的。我已经在这个项目上达成绝大多数必要的功能。而更加优秀的[Trials Frontier Revival Project](https://trialsproject.com/)已经公开发布，那么这个项目唯一的优势也只有开源了。  
关于 **我是否可以帮助这个项目** :  
当然，你当然可以帮助这个项目。我个人非常欢迎所有喜爱特技摩托前线这个游戏的玩家或开发者来帮助这个项目变得更好。  
无论你是否对这个项目感兴趣，我都感谢你看到这里。  


## 开源许可证
GPL-v3 Only:[LICENSE](LICENSE)  