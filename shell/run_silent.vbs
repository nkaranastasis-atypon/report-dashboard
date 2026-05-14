Set oShell = CreateObject("WScript.Shell")
Dim rootDir
rootDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
rootDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(rootDir)
oShell.CurrentDirectory = rootDir
oShell.Run "python.exe server.py", 0, False