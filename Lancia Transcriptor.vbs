Dim WShell
Set WShell = CreateObject("WScript.Shell")
WShell.CurrentDirectory = "C:\Users\fran_\Desktop\Transcriber_Pro"
WShell.Run """C:\Users\fran_\Desktop\Transcriber_Pro\venv\Scripts\pythonw.exe"" main.py", 0, False
Set WShell = Nothing
