' Avvia Transcriber Pro (interfaccia predefinita, la web UI) senza finestra di console. Percorsi relativi a questo file: va bene ovunque sia la cartella.
Dim WShell, Fso, Here
Set WShell = CreateObject("WScript.Shell")
Set Fso = CreateObject("Scripting.FileSystemObject")
Here = Fso.GetParentFolderName(WScript.ScriptFullName)
WShell.CurrentDirectory = Here
WShell.Run """" & Here & "\venv\Scripts\pythonw.exe"" main.py", 0, False
Set Fso = Nothing
Set WShell = Nothing
