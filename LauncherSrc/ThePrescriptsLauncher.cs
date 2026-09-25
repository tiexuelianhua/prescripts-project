// Launches the Prescripts app (app.py, its multi-page entry point) in a
// plain native window (desktop_app.py -- a pywebview window around the same
// local Streamlit server) rather than a browser tab.
//
// Compiled to a real .exe (rather than wrapping the .vbs in wscript.exe or
// packaging it with iexpress) because Windows won't offer "Pin to taskbar"
// for a shortcut whose target isn't a genuine executable, and iexpress
// self-extracting packages get auto-flagged by Windows' installer-detection
// heuristic as needing elevation -- which by itself also disables pinning.
// A plain csc.exe-compiled .exe carries a default asInvoker manifest, so it
// triggers neither problem.
//
// If the app is already open, a launch just brings its window forward.
// Otherwise every launch first stops whatever is already serving on Port, then starts
// desktop_app.py, which starts its own fresh server there (and separately
// closes any previous *window* left over from an earlier launch -- see its
// own _kill_previous_instance). This process itself runs hidden (pythonw.exe,
// no console) -- without the port cleanup below, each click left another
// server running on the next free port (8502, 8503, ... ended up at 20 of
// them), old code kept being served from stale ones, and Spotify's OAuth
// redirect (fixed at 8501) landed on the wrong server. The port is passed
// explicitly (inside desktop_app.py) for the same reason: Streamlit
// otherwise silently falls back to the next free port.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Threading;

class ThePrescriptsLauncher
{
    // Must match REDIRECT_URI in spotify_data.py.
    const int Port = 8501;
    // Must match PID_FILE in desktop_app.py.
    const string PidFile = @"C:\Users\echoj\The Prescripts\Scripts\.desktop_app.pid";

    const int SW_RESTORE = 9;
    delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] static extern int GetWindowTextLength(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd, int cmd);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);

    // Any arguments are passed on to desktop_app.py -- the Startup-folder
    // shortcut uses this for --minimized. Only simple flags are ever
    // passed, so plain quoting is enough.
    static void Main(string[] args)
    {
        // Already open (e.g. the minimised copy the Startup shortcut opened):
        // just bring that window up. Restarting here used to throw that
        // copy away and reopen it un-minimised. Closing the window quits the
        // app, so the next launch after that is a fresh start anyway.
        IntPtr existing = FindExistingWindow();
        if (existing != IntPtr.Zero)
        {
            if (Array.IndexOf(args, "--minimized") < 0)
            {
                if (IsIconic(existing))
                    ShowWindow(existing, SW_RESTORE);
                SetForegroundWindow(existing);
            }
            return;
        }

        StopExistingServer();

        string forwarded = "";
        foreach (string arg in args)
            forwarded += " \"" + arg + "\"";

        var psi = new ProcessStartInfo
        {
            // pythonw.exe, not python.exe: this process holds the actual
            // window open until the user closes it (desktop_app.py's
            // webview.start() blocks), so it's not just something whose
            // startup console needs hiding -- it should never have a
            // console at all.
            FileName = @"C:\Users\echoj\The Prescripts\Scripts\.venv\Scripts\pythonw.exe",
            Arguments = "\"C:\\Users\\echoj\\The Prescripts\\Scripts\\desktop_app.py\"" + forwarded,
            WorkingDirectory = @"C:\Users\echoj\The Prescripts\Scripts",
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        Process.Start(psi);
    }

    // The visible window of the process desktop_app.py recorded in its
    // pidfile, if that process is still alive and is Python (a stale
    // pidfile's PID could have been reused by anything since).
    static IntPtr FindExistingWindow()
    {
        int pid;
        try
        {
            if (!int.TryParse(File.ReadAllText(PidFile).Trim(), out pid))
                return IntPtr.Zero;
            if (!Process.GetProcessById(pid).ProcessName.StartsWith("python", StringComparison.OrdinalIgnoreCase))
                return IntPtr.Zero;
        }
        catch (Exception)
        {
            return IntPtr.Zero;
        }

        IntPtr found = IntPtr.Zero;
        EnumWindows((hwnd, _) =>
        {
            uint owner;
            GetWindowThreadProcessId(hwnd, out owner);
            if (owner == pid && IsWindowVisible(hwnd) && GetWindowTextLength(hwnd) > 0)
            {
                found = hwnd;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    static void StopExistingServer()
    {
        foreach (int pid in ListeningPids())
        {
            try
            {
                // Only ever stop a Python process -- something else that
                // happens to hold the port isn't ours to kill.
                if (!Process.GetProcessById(pid).ProcessName.StartsWith("python", StringComparison.OrdinalIgnoreCase))
                    continue;
            }
            catch (Exception)
            {
                // Already gone, or mid-exit (GetProcessById can succeed on a
                // dying process and then throw from ProcessName). This
                // exe has no window, so an unhandled exception here would
                // just silently kill the launcher before it starts anything.
                continue;
            }

            var taskkill = Process.Start(new ProcessStartInfo
            {
                FileName = "taskkill.exe",
                Arguments = "/PID " + pid + " /T /F",
                UseShellExecute = false,
                CreateNoWindow = true,
            });
            taskkill.WaitForExit();
        }

        // The OS can take a moment to actually release the port after the
        // process dies, and a new server launched into a still-held port
        // just exits (Streamlit is told an explicit port, so it doesn't fall
        // back to another) -- so wait for it to be free rather than guess.
        for (int i = 0; i < 50 && ListeningPids().Count > 0; i++)
            Thread.Sleep(100);
    }

    static List<int> ListeningPids()
    {
        var netstat = Process.Start(new ProcessStartInfo
        {
            FileName = "netstat.exe",
            Arguments = "-ano",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            CreateNoWindow = true,
        });
        string output = netstat.StandardOutput.ReadToEnd();
        netstat.WaitForExit();

        var listening = new Regex(@"^\s*TCP\s+\S+:" + Port + @"\s+\S+\s+LISTENING\s+(\d+)\s*$",
                                  RegexOptions.Multiline);
        var pids = new List<int>();
        foreach (Match match in listening.Matches(output))
        {
            // One server shows up twice (an IPv4 and an IPv6 listener).
            int pid = int.Parse(match.Groups[1].Value);
            if (!pids.Contains(pid))
                pids.Add(pid);
        }
        return pids;
    }
}
