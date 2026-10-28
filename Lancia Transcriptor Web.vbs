' Avvia Transcriber Pro (interfaccia web) senza finestra di console. Percorsi relativi a questo file: va bene ovunque sia la cartella.
Dim WShell, Fso, Here
Set WShell = CreateObject("WScript.Shell")
Set Fso = CreateObject("Scripting.FileSystemObject")
Here = Fso.GetParentFolderName(WScript.ScriptFullName)
WShell.CurrentDirectory = Here
WShell.Run """" & Here & "\venv\Scripts\pythonw.exe"" main.py --ui web", 0, False
Set Fso = Nothing
Set WShell = Nothing
