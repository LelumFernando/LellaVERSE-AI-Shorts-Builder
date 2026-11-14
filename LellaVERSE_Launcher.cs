using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Windows.Forms;

namespace LellaVERSE
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            string appDir = AppDomain.CurrentDomain.BaseDirectory;
            Directory.SetCurrentDirectory(appDir);

            // 1. Ensure bin folder (bundled FFmpeg) is in PATH
            string binDir = Path.Combine(appDir, "bin");
            if (Directory.Exists(binDir))
            {
                string path = Environment.GetEnvironmentVariable("PATH") ?? "";
                Environment.SetEnvironmentVariable("PATH", binDir + Path.PathSeparator + path);
            }

            // 2. Check Python executable
            string pythonExe = Path.Combine(appDir, "venv", "Scripts", "python.exe");
            if (!File.Exists(pythonExe))
            {
                pythonExe = Path.Combine(appDir, "python", "python.exe");
            }
            if (!File.Exists(pythonExe))
            {
                pythonExe = "python.exe";
            }

            // 3. Check if Streamlit is already running on port 8501
            bool isRunning = IsPortOpen("127.0.0.1", 8501, 500);
            if (!isRunning)
            {
                // Start Streamlit in background
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = pythonExe,
                    Arguments = "-m streamlit run app.py --server.headless true --browser.gatherUsageStats false",
                    WorkingDirectory = appDir,
                    WindowStyle = ProcessWindowStyle.Hidden,
                    CreateNoWindow = true,
                    UseShellExecute = false
                };

                try
                {
                    Process.Start(psi);
                }
                catch (Exception ex)
                {
                    MessageBox.Show("Failed to launch LellaVERSE background server:\n" + ex.Message,
                        "LellaVERSE AI Shorts Builder", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                // Wait for server health endpoint
                for (int i = 0; i < 20; i++)
                {
                    Thread.Sleep(500);
                    if (IsPortOpen("127.0.0.1", 8501, 400))
                    {
                        break;
                    }
                }
            }

            // 4. Open Application in sleek app mode or default browser
            OpenBrowser("http://localhost:8501");
        }

        static bool IsPortOpen(string host, int port, int timeoutMs)
        {
            try
            {
                using (TcpClient client = new TcpClient())
                {
                    IAsyncResult result = client.BeginConnect(host, port, null, null);
                    bool success = result.AsyncWaitHandle.WaitOne(timeoutMs);
                    if (success)
                    {
                        client.EndConnect(result);
                        return true;
                    }
                    return false;
                }
            }
            catch
            {
                return false;
            }
        }

        static void OpenBrowser(string url)
        {
            string edge = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
                "Microsoft", "Edge", "Application", "msedge.exe");
            if (!File.Exists(edge))
            {
                edge = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                    "Microsoft", "Edge", "Application", "msedge.exe");
            }

            string chrome = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                "Google", "Chrome", "Application", "chrome.exe");
            if (!File.Exists(chrome))
            {
                chrome = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
                    "Google", "Chrome", "Application", "chrome.exe");
            }
            if (!File.Exists(chrome))
            {
                chrome = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Google", "Chrome", "Application", "chrome.exe");
            }

            try
            {
                if (File.Exists(edge))
                {
                    Process.Start(edge, "--app=" + url);
                    return;
                }
                if (File.Exists(chrome))
                {
                    Process.Start(chrome, "--app=" + url);
                    return;
                }
                Process.Start(url);
            }
            catch
            {
                try { Process.Start(url); } catch { }
            }
        }
    }
}
