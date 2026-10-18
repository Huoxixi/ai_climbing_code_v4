using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class AiClimbing {
    [STAThread]
    static int Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, "runtime", "pythonw.exe");
        if (!File.Exists(python)) {
            MessageBox.Show("请先解压完整程序包，再双击启动。", "攀岩桌面版");
            return 1;
        }
        try {
            string signalDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AiClimbing", "tmp");
            Directory.CreateDirectory(signalDir);
            string signal = Path.Combine(signalDir, Guid.NewGuid().ToString("N") + ".ready");
            ProcessStartInfo info = new ProcessStartInfo(python, "-B -X utf8 -m desktop.launcher --ready-file \"" + signal + "\"");
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            Process process = null;
            bool ready = false;
            Form splash = new Form();
            splash.Text = "攀岩桌面版";
            splash.Width = 430; splash.Height = 150;
            splash.StartPosition = FormStartPosition.CenterScreen;
            splash.FormBorderStyle = FormBorderStyle.FixedDialog;
            splash.MaximizeBox = false;
            Label label = new Label();
            label.Text = "正在校验资源并启动本机服务，请稍候…";
            label.Dock = DockStyle.Top; label.Height = 48;
            label.TextAlign = System.Drawing.ContentAlignment.MiddleCenter;
            splash.Controls.Add(label);
            ProgressBar bar = new ProgressBar();
            bar.Dock = DockStyle.Bottom; bar.Style = ProgressBarStyle.Marquee;
            splash.Controls.Add(bar);
            System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
            timer.Interval = 200;
            timer.Tick += delegate {
                if (File.Exists(signal) || (process != null && process.HasExited)) {
                    ready = true; timer.Stop(); splash.Close();
                }
            };
            splash.Shown += delegate { process = Process.Start(info); timer.Start(); };
            Application.Run(splash);
            timer.Dispose();
            if (File.Exists(signal)) File.Delete(signal);
            if (process == null) return 1;
            if (!ready && !process.HasExited) process.Kill();
            process.WaitForExit();
            return process.ExitCode;
        } catch {
            MessageBox.Show("程序无法启动，请检查使用说明中的 Windows 环境要求。", "攀岩桌面版");
            return 1;
        }
    }
}
