import tkinter as tk
import threading
import json
import time
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import serial


class GUICurtain:
    def __init__(self, ser):
        """
        Initialize the GUI for the curtain control panel.
        :param ser: serial.Serial object for communication with the Pico
        """
        self.ser = ser
        self.root = tk.Tk()
        self.root.geometry("900x1000")
        self.root.title("Pico Control Panel")
        self.max_points = 100

        self._build_threshold_inputs()
        self._build_labels()
        self._build_plot()
        self._build_log()

        self.temperature_data = []
        self.humidity_data = []
        self.light_data = []

        # Start the serial reading thread
        self.thread = threading.Thread(target=self.read_from_serial, daemon=True)
        self.thread.start()

    def _build_threshold_inputs(self):
        """
        Build the input fields for temperature and humidity thresholds.
        """
        tk.Label(self.root, text="Temperature Threshold：").pack()
        self.entry_temp = tk.Entry(self.root)
        self.entry_temp.pack()

        tk.Label(self.root, text="Humidity Threshold").pack()
        self.entry_humid = tk.Entry(self.root)
        self.entry_humid.pack()

        tk.Label(self.root, text="Light Threshold").pack()
        self.entry_light = tk.Entry(self.root)
        self.entry_light.pack()

        tk.Label(self.root, text="Threshold priority selection：").pack()
        self.priority_var = tk.StringVar(self.root)
        self.priority_var.set("temperature")

        priority_options = ["temperature", "humidity", "light"]
        tk.OptionMenu(self.root, self.priority_var, *priority_options).pack()

        self.label_status = tk.Label(self.root, text="")
        self.label_status.pack()

        btn_send = tk.Button(self.root, text="Send thresholds", command=self.send_threshold)
        btn_send.pack(pady=5)

    def _build_labels(self):
        """
        Build the labels to display the current status of the curtain collected by Pico.
        """
        self.labels = {}
        self.fields = [
            "temperature", "humidity", "light",
            "curtain_status", "thresholds_status", "sensor_status", "timestamp"
        ]
        for field in self.fields:
            frame = tk.Frame(self.root)
            frame.pack()
            tk.Label(frame, text=f"{field}:").pack(side=tk.LEFT)
            self.labels[field] = tk.Label(frame, text="")
            self.labels[field].pack(side=tk.LEFT)

    def _build_plot(self):
        """
        Build the plot for real-time data visualization.
        """
        self.fig, self.ax = plt.subplots(figsize=(6, 5))
        self.line_temp, = self.ax.plot([], [], label="Temperature")
        self.line_humid, = self.ax.plot([], [], label="Humidity")
        self.line_light, = self.ax.plot([], [], label="Light")
        self.ax.set_ylim(0, 120)
        self.ax.set_xlim(0, self.max_points)
        self.ax.set_xlabel("Time(s)")
        self.ax.set_title("Real-time Data Plot")
        self.ax.legend()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        self.canvas.get_tk_widget().pack()

    def _build_log(self):
        """
        Build the log area to display messages.
        """
        self.label_log = tk.Label(self.root, text="Log:")
        self.label_log.pack()
        self.output_text = tk.Text(self.root, height=5, width=100)
        self.output_text.pack()

    def append_text(self, text):
        """
        Append text to the log area.
        :param text: text to append
        """
        self.output_text.insert(tk.END, text + "\n")
        self.output_text.see(tk.END)

    def send_threshold(self):
        """
        Send the temperature and humidity thresholds to the Pico.
        """
        temp = self.entry_temp.get()
        humid = self.entry_humid.get()
        light = self.entry_light.get()
        priority = self.priority_var.get()

        if temp.isdigit() and humid.isdigit():
            data = {
                "temperature": float(temp),
                "humidity": float(humid),
                "light": float(light),
                "priority": priority
            }
            self.ser.write((json.dumps(data) + "\n").encode())
            self.label_status.config(text=f"Sent: Temperature={temp}, Humidity={humid}, Light={light}, Priority:{priority}")
        else:
            self.label_status.config(text="Please enter valid numbers.")

    def update_plot(self):
        """
        Update the plot with the latest data.
        """
        self.line_temp.set_data(range(len(self.temperature_data)), self.temperature_data)
        self.line_humid.set_data(range(len(self.humidity_data)), self.humidity_data)
        self.line_light.set_data(range(len(self.light_data)), self.light_data)
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw()

    def read_from_serial(self):
        """
        Read data from the serial port and update the GUI.
        """
        while True:
            try:
                line = self.ser.readline().decode('utf-8').strip()
                if not line:
                    continue
                if line.startswith("{") and line.endswith("}"):
                    data = json.loads(line)

                    for key in self.fields:
                        if key in data:
                            value = data[key]
                            # Adding unit based on key
                            if key == "temperature":
                                display = f"{value} °C"
                            elif key == "humidity":
                                display = f"{value} %"
                            elif key == "light":
                                display = f"{value} lux"
                            else:
                                display = str(value)
                            self.root.after(0, self.labels[key].config, {'text': display})

                    self.temperature_data.append(data.get("temperature", 0))
                    self.humidity_data.append(data.get("humidity", 0))
                    self.light_data.append(data.get("light", 0))
                    if len(self.temperature_data) > self.max_points:
                        self.temperature_data = self.temperature_data[-self.max_points:]
                        self.humidity_data = self.humidity_data[-self.max_points:]
                        self.light_data = self.light_data[-self.max_points:]

                    self.root.after(0, self.update_plot)

                    if line:
                        self.root.after(0, self.append_text, "Data received from Pico")
                    else:
                        self.root.after(0, self.append_text, "No data received from Pico")
                else:
                    self.root.after(0, self.append_text, line)

            except Exception as e:
                self.root.after(0, self.append_text, f"Error: {e}")
                break

    def run(self):
        """
        Run the main loop of the GUI.
        """
        self.root.mainloop()


if __name__ == "__main__":
    # Initialize the serial connection
    ser = serial.Serial('COM3', 115200, timeout=1)

    # Reset and initialize the Pico
    ser.write(b'\x02')
    time.sleep(0.5)
    ser.write(b'\x04')

    # Main program
    gui = GUICurtain(ser)
    gui.run()
