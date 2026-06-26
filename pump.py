import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial
import serial.tools.list_ports
import threading
import time


class SyringePumpGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Syringe Pump Controller")
        self.root.geometry("820x700")

        # 這個數值已經包含 microstepping。
        # Arduino 端不要再乘 16。
        # 55.344 表示 50 uL 約等於 2767 steps。
        # 如果實際還是跑太多，就要調小這個值。
        self.STEPS_PER_UL = 55.344

        self.MAX_CMD_STEPS = 99999

        self.serial_conn = None
        self.is_running = True

        self.task_queue = []
        self.is_executing_queue = False
        self.is_paused = False

        self.operation_start_time = None
        self.pause_start_time = None
        self.paused_total_time = 0.0
        self.timer_job = None

        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("TLabel", font=("Microsoft JhengHei", 10))
        style.configure("TButton", font=("Microsoft JhengHei", 10))
        style.configure(
            "TLabelframe.Label",
            font=("Microsoft JhengHei", 10, "bold"),
            foreground="#2C3E50",
        )

        self.create_widgets()

        self.monitor_thread = threading.Thread(target=self.read_serial_data, daemon=True)
        self.monitor_thread.start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        conn_frame = ttk.LabelFrame(self.root, text=" 連線設定 ", padding=10)
        conn_frame.pack(fill="x", padx=15, pady=5)

        ttk.Label(conn_frame, text="Serial Port:").grid(row=0, column=0, padx=5)

        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(conn_frame, textvariable=self.port_var, width=12)
        self.port_combo.grid(row=0, column=1, padx=5)

        ttk.Button(conn_frame, text="刷新", command=self.refresh_ports).grid(row=0, column=2, padx=5)

        self.conn_btn = ttk.Button(conn_frame, text="連接 Arduino", command=self.toggle_connection)
        self.conn_btn.grid(row=0, column=3, padx=10)

        self.status_label = ttk.Label(
            conn_frame,
            text="未連接",
            foreground="#E74C3C",
            font=("Microsoft JhengHei", 10, "bold"),
        )
        self.status_label.grid(row=0, column=4, padx=15)

        self.refresh_ports()

        mid_frame = ttk.Frame(self.root)
        mid_frame.pack(fill="both", expand=True, padx=15, pady=5)

        param_frame = ttk.LabelFrame(mid_frame, text=" 幫浦參數 ", padding=10)
        param_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        ttk.Label(param_frame, text="體積 (uL):").grid(row=0, column=0, sticky="w", pady=10)

        self.vol_var = tk.StringVar(value="50")
        self.vol_entry = ttk.Entry(
            param_frame,
            textvariable=self.vol_var,
            font=("Consolas", 12, "bold"),
            width=10,
            justify="center",
        )
        self.vol_entry.grid(row=0, column=1, padx=10)
        self.vol_entry.bind("<KeyRelease>", self.update_calc_label)

        ttk.Label(param_frame, text="速度 (uL/min):").grid(row=1, column=0, sticky="w", pady=10)

        self.speed_var = tk.StringVar(value="500")
        self.speed_entry = ttk.Entry(
            param_frame,
            textvariable=self.speed_var,
            font=("Consolas", 12, "bold"),
            width=10,
            justify="center",
        )
        self.speed_entry.grid(row=1, column=1, padx=10)
        self.speed_entry.bind("<KeyRelease>", self.update_calc_label)

        ttk.Label(param_frame, text="方向:").grid(row=2, column=0, sticky="w", pady=10)

        self.dir_var = tk.StringVar(value="d1 推")
        self.dir_combo = ttk.Combobox(
            param_frame,
            textvariable=self.dir_var,
            values=["d1 推", "d0 退"],
            state="readonly",
            width=12,
        )
        self.dir_combo.grid(row=2, column=1, padx=10, sticky="w")

        self.calc_label = ttk.Label(
            param_frame,
            text="步數: 0 steps\n速度: 0 steps/s",
            foreground="#7F8C8D",
            font=("Microsoft JhengHei", 9),
        )
        self.calc_label.grid(row=3, column=0, columnspan=2, pady=(0, 10), sticky="w")

        self.timer_label = ttk.Label(
            param_frame,
            text="總經過: 0.0 s\n動作時間: 0.0 s",
            foreground="#2980B9",
            font=("Consolas", 12, "bold"),
        )
        self.timer_label.grid(row=4, column=0, columnspan=2, pady=(0, 10), sticky="w")

        self.add_btn = tk.Button(
            param_frame,
            text="加入任務",
            bg="#F39C12",
            fg="white",
            font=("Microsoft JhengHei", 10, "bold"),
            command=self.add_to_queue,
        )
        self.add_btn.grid(row=5, column=0, columnspan=2, pady=5, sticky="ew")

        control_frame = ttk.LabelFrame(param_frame, text=" 控制 ", padding=8)
        control_frame.grid(row=6, column=0, columnspan=2, sticky="ew", pady=8)

        self.run_q_btn = tk.Button(
            control_frame,
            text="開始執行",
            bg="#2ECC71",
            fg="white",
            font=("Microsoft JhengHei", 10, "bold"),
            command=self.start_queue_execution,
        )
        self.run_q_btn.grid(row=0, column=0, padx=3, pady=3, sticky="ew")

        self.pause_btn = tk.Button(
            control_frame,
            text="暫停",
            bg="#F1C40F",
            fg="black",
            font=("Microsoft JhengHei", 10, "bold"),
            command=self.pause_queue,
            state="disabled",
        )
        self.pause_btn.grid(row=0, column=1, padx=3, pady=3, sticky="ew")

        self.resume_btn = tk.Button(
            control_frame,
            text="繼續",
            bg="#3498DB",
            fg="white",
            font=("Microsoft JhengHei", 10, "bold"),
            command=self.resume_queue,
            state="disabled",
        )
        self.resume_btn.grid(row=1, column=0, padx=3, pady=3, sticky="ew")

        self.stop_btn = tk.Button(
            control_frame,
            text="停止",
            bg="#E74C3C",
            fg="white",
            font=("Microsoft JhengHei", 10, "bold"),
            command=self.stop_current_motion,
            state="disabled",
        )
        self.stop_btn.grid(row=1, column=1, padx=3, pady=3, sticky="ew")

        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)

        queue_frame = ttk.LabelFrame(mid_frame, text=" 任務佇列 ", padding=10)
        queue_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

        self.queue_listbox = tk.Listbox(queue_frame, font=("Consolas", 9), height=8)
        self.queue_listbox.pack(fill="both", expand=True, pady=5)

        q_btn_frame = ttk.Frame(queue_frame)
        q_btn_frame.pack(fill="x")

        self.clear_q_btn = ttk.Button(q_btn_frame, text="清空任務", command=self.clear_queue)
        self.clear_q_btn.pack(side="left", fill="x", expand=True, padx=2)

        monitor_frame = ttk.LabelFrame(self.root, text=" Arduino Serial Monitor ", padding=5)
        monitor_frame.pack(fill="both", expand=True, padx=15, pady=5)

        self.monitor_text = scrolledtext.ScrolledText(
            monitor_frame,
            height=10,
            state="disabled",
            bg="#1E1E1E",
            fg="#00FF00",
            font=("Consolas", 10),
        )
        self.monitor_text.pack(fill="both", expand=True)

        self.update_calc_label()

    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports

        if ports:
            self.port_combo.current(0)
        else:
            self.port_var.set("")

    def toggle_connection(self):
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            self.conn_btn.config(text="連接 Arduino")
            self.status_label.config(text="未連接", foreground="#E74C3C")
            self.log_monitor("[系統] Serial disconnected")
            return

        try:
            port = self.port_var.get().strip()

            if not port:
                messagebox.showwarning("提醒", "請先選擇 Serial Port")
                return

            self.serial_conn = serial.Serial(port, 9600, timeout=0.1)
            time.sleep(2.0)
            self.serial_conn.reset_input_buffer()

            self.conn_btn.config(text="中斷連線")
            self.status_label.config(text=f"已連接 {port}", foreground="#27AE60")
            self.log_monitor(f"[系統] Connected to {port}")

        except Exception as e:
            messagebox.showerror("連線錯誤", f"無法連接 {port}\n{e}")

    def read_serial_data(self):
        while self.is_running:
            if self.serial_conn and self.serial_conn.is_open:
                try:
                    line = self.serial_conn.readline().decode("utf-8", errors="ignore").strip()
                    if line:
                        self.root.after(0, self.handle_serial_line, line)
                except Exception:
                    pass

            time.sleep(0.03)

    def handle_serial_line(self, line):
        self.log_monitor(f">> {line}")

        if line == "DONE":
            if self.is_executing_queue and not self.is_paused:
                self.execute_next_task()
            return

        if line == "PAUSED":
            self.set_paused_state()
            return

        if line == "RESUMED":
            self.set_running_state_after_resume()
            return

        if line == "STOPPED":
            if self.is_executing_queue or self.is_paused:
                self.stop_queue("Stopped by user")
            return

        if line.startswith("ERR"):
            self.stop_queue(f"Arduino error: {line}")
            return

    def log_monitor(self, message):
        self.monitor_text.config(state="normal")
        self.monitor_text.insert("end", message + "\n")
        self.monitor_text.see("end")
        self.monitor_text.config(state="disabled")

    def update_calc_label(self, event=None):
        try:
            vol_ul = float(self.vol_var.get().strip())
            speed_ul_min = float(self.speed_var.get().strip())

            if vol_ul <= 0 or speed_ul_min <= 0:
                raise ValueError

            steps = round(vol_ul * self.STEPS_PER_UL)
            speed_steps = round((speed_ul_min / 60.0) * self.STEPS_PER_UL)

            self.calc_label.config(
                text=f"步數: {steps} steps\n速度: {speed_steps} steps/s",
                foreground="#2C3E50",
            )

        except ValueError:
            self.calc_label.config(
                text="步數: 0 steps\n速度: 0 steps/s",
                foreground="#E74C3C",
            )

    def add_to_queue(self):
        try:
            vol_ul = float(self.vol_var.get().strip())
            speed_ul_min = float(self.speed_var.get().strip())

            if vol_ul <= 0 or speed_ul_min <= 0:
                messagebox.showwarning("提醒", "體積和速度必須大於 0")
                return

            direction_text = self.dir_var.get()
            direction = 1 if direction_text.startswith("d1") else 0
            direction_name = "推" if direction == 1 else "退"

            total_steps = round(vol_ul * self.STEPS_PER_UL)
            speed_steps = round((speed_ul_min / 60.0) * self.STEPS_PER_UL)

            if total_steps <= 0:
                messagebox.showwarning("提醒", "體積太小，換算後步數為 0")
                return

            if speed_steps <= 0:
                messagebox.showwarning("提醒", "速度太小，換算後 steps/s 為 0")
                return

            if speed_steps > self.MAX_CMD_STEPS:
                messagebox.showwarning("提醒", "速度太大，超過 Arduino 5 位數封包限制")
                return

            remaining_steps = total_steps
            chunks = []

            while remaining_steps > 0:
                chunk = min(remaining_steps, self.MAX_CMD_STEPS)
                chunks.append(chunk)
                remaining_steps -= chunk

            for index, chunk_steps in enumerate(chunks):
                steps_str = str(chunk_steps).zfill(5)
                speed_str = str(speed_steps).zfill(5)
                cmd = f"d{steps_str}v00000v{speed_str}d{direction}\r"

                actual_ul = chunk_steps / self.STEPS_PER_UL
                estimate_sec = chunk_steps / speed_steps

                part = ""
                if len(chunks) > 1:
                    part = f" part {index + 1}/{len(chunks)}"

                display = (
                    f"[d{direction} {direction_name}] "
                    f"{actual_ul:.2f} uL @ {speed_ul_min:g} uL/min "
                    f"(est {estimate_sec:.1f}s){part}"
                )

                task = {
                    "cmd": cmd,
                    "display": display,
                }

                self.task_queue.append(task)
                self.queue_listbox.insert("end", display)

            self.log_monitor(f"[系統] Added {len(chunks)} task(s)")

        except ValueError:
            messagebox.showerror("錯誤", "請輸入正確數字")

    def clear_queue(self):
        if self.is_executing_queue or self.is_paused:
            messagebox.showwarning("提醒", "執行中不能清空任務，請先停止")
            return

        self.task_queue.clear()
        self.queue_listbox.delete(0, "end")

    def start_queue_execution(self):
        if not self.serial_conn or not self.serial_conn.is_open:
            messagebox.showwarning("提醒", "請先連接 Arduino")
            return

        if not self.task_queue:
            messagebox.showinfo("提醒", "任務佇列是空的")
            return

        if self.is_executing_queue:
            return

        self.is_executing_queue = True
        self.is_paused = False

        self.start_timer()
        self.set_control_state("running")

        self.log_monitor("[系統] Start queue")
        self.execute_next_task()

    def execute_next_task(self):
        if not self.is_executing_queue or self.is_paused:
            return

        if not self.task_queue:
            self.is_executing_queue = False
            self.set_control_state("idle")
            self.finish_timer()
            self.log_monitor("[系統] All tasks finished")
            return

        task = self.task_queue.pop(0)
        self.queue_listbox.delete(0)

        try:
            self.serial_conn.write(task["cmd"].encode("ascii"))
            self.serial_conn.flush()
            self.log_monitor(f"[PC送出] {task['display']} | packet: {task['cmd'].strip()}")

        except Exception as e:
            self.stop_queue(f"Serial write failed: {e}")

    def pause_queue(self):
        if not self.is_executing_queue or self.is_paused:
            return

        self.send_control_command("P", "PAUSE")

    def resume_queue(self):
        if not self.is_executing_queue or not self.is_paused:
            return

        self.send_control_command("R", "RESUME")

    def stop_current_motion(self):
        if not self.is_executing_queue and not self.is_paused:
            return

        self.task_queue.clear()
        self.queue_listbox.delete(0, "end")

        self.send_control_command("S", "STOP")

    def send_control_command(self, command, name):
        try:
            self.serial_conn.write((command + "\r").encode("ascii"))
            self.serial_conn.flush()
            self.log_monitor(f"[PC送出] {name}")
        except Exception as e:
            self.stop_queue(f"Serial write failed: {e}")

    def set_paused_state(self):
        if not self.is_executing_queue:
            return

        if not self.is_paused:
            self.pause_start_time = time.monotonic()

        self.is_paused = True
        self.set_control_state("paused")
        self.log_monitor("[系統] Paused")

    def set_running_state_after_resume(self):
        if not self.is_executing_queue:
            return

        if self.is_paused and self.pause_start_time is not None:
            self.paused_total_time += time.monotonic() - self.pause_start_time

        self.pause_start_time = None
        self.is_paused = False

        self.set_control_state("running")
        self.log_monitor("[系統] Resumed")

    def stop_queue(self, reason):
        self.is_executing_queue = False
        self.is_paused = False
        self.pause_start_time = None

        self.task_queue.clear()
        self.queue_listbox.delete(0, "end")

        self.set_control_state("idle")
        self.finish_timer()

        self.log_monitor(f"[系統] Queue stopped: {reason}")

    def set_control_state(self, state):
        if state == "idle":
            self.run_q_btn.config(text="開始執行", state="normal", bg="#2ECC71")
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="disabled")
            self.stop_btn.config(state="disabled")
            self.clear_q_btn.config(state="normal")

        elif state == "running":
            self.run_q_btn.config(text="執行中...", state="disabled", bg="#95A5A6")
            self.pause_btn.config(state="normal")
            self.resume_btn.config(state="disabled")
            self.stop_btn.config(state="normal")
            self.clear_q_btn.config(state="disabled")

        elif state == "paused":
            self.run_q_btn.config(text="已暫停", state="disabled", bg="#95A5A6")
            self.pause_btn.config(state="disabled")
            self.resume_btn.config(state="normal")
            self.stop_btn.config(state="normal")
            self.clear_q_btn.config(state="disabled")

    def start_timer(self):
        self.operation_start_time = time.monotonic()
        self.pause_start_time = None
        self.paused_total_time = 0.0

        if self.timer_job is not None:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None

        self.update_timer()

    def update_timer(self):
        if self.operation_start_time is None:
            return

        now = time.monotonic()

        total_elapsed = now - self.operation_start_time
        active_elapsed = total_elapsed - self.paused_total_time

        if self.is_paused and self.pause_start_time is not None:
            active_elapsed -= now - self.pause_start_time

        if active_elapsed < 0:
            active_elapsed = 0

        self.timer_label.config(
            text=f"總經過: {total_elapsed:.1f} s\n動作時間: {active_elapsed:.1f} s"
        )

        self.timer_job = self.root.after(200, self.update_timer)

    def finish_timer(self):
        if self.timer_job is not None:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None

        if self.operation_start_time is not None:
            now = time.monotonic()

            total_elapsed = now - self.operation_start_time
            active_elapsed = total_elapsed - self.paused_total_time

            if self.is_paused and self.pause_start_time is not None:
                active_elapsed -= now - self.pause_start_time

            if active_elapsed < 0:
                active_elapsed = 0

            self.timer_label.config(
                text=f"總經過: {total_elapsed:.1f} s\n動作時間: {active_elapsed:.1f} s"
            )

    def on_closing(self):
        self.is_running = False

        if self.timer_job is not None:
            self.root.after_cancel(self.timer_job)

        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()

        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SyringePumpGUI(root)
    root.mainloop()