// Launches the Meal Receipts Streamlit app with no visible window.
//
// Compiled to a real .exe (rather than wrapping the .vbs in wscript.exe or
// packaging it with iexpress) because Windows won't offer "Pin to taskbar"
// for a shortcut whose target isn't a genuine executable, and iexpress
// self-extracting packages get auto-flagged by Windows' installer-detection
// heuristic as needing elevation -- which by itself also disables pinning.
// A plain csc.exe-compiled .exe carries a default asInvoker manifest, so it
// triggers neither problem.
using System.Diagnostics;

class MealReceiptsLauncher
{
    static void Main()
    {
        var psi = new ProcessStartInfo
        {
            FileName = @"C:\Users\echoj\The Prescripts\Scripts\.venv\Scripts\python.exe",
            Arguments = "-m streamlit run \"C:\\Users\\echoj\\The Prescripts\\Scripts\\mealReceiptsApp_cV.py\"",
            WorkingDirectory = @"C:\Users\echoj\The Prescripts\Scripts",
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        Process.Start(psi);
    }
}
