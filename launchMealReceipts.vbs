' Launches the Meal Receipts Streamlit app with no visible console window.
' Wrapped in .vbs (rather than .bat) because WScript.Shell.Run can launch a
' process with a hidden window (windowStyle 0); a .bat would flash a console.
Set objShell = CreateObject("WScript.Shell")
scriptsDir = "C:\Users\echoj\The Prescripts\Scripts"
objShell.CurrentDirectory = scriptsDir
pythonExe = scriptsDir & "\.venv\Scripts\python.exe"
appScript = scriptsDir & "\mealReceiptsApp_cV.py"
objShell.Run """" & pythonExe & """ -m streamlit run """ & appScript & """", 0, False
