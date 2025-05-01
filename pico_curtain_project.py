from machine import Pin, ADC
import dht
import time
import sys
import ujson
import select
import math
import uasyncio as asyncio

# Setting default parameters
DHT_PIN_IN = 16
DHT_PIN_OUT = 17
LIGHT_PIN_IN = 26
LIGHT_PIN_OUT = 27
VOLTAGE = 3.3
R_FIXED = 10000.0
R10 = 15000.0
GAMMA = 0.6
ADC_MAX = 65535

DEFAULT_DELAY = 0.001
STEPS_DOWN = 512 * 2
STEPS_UP = 512 * 3
TIME_INTERVAL = 0.5  # seconds
TIME_TOTAL = 60*60 # seconds
CURRENT_CURTAIN_STATUS = 0  # 0: open, 1: closed

DEFAULT_THRESHOLDS = {
    "temperature": 40,
    "humidity": 60,
    "light": 100,
    "priority": "temperature"
}

DEFAULT_STATUS = {
    "temperature_in": 0,
    "humidity_in": 0,
    "light_in": 0,
    "temperature_out": 0,
    "humidity_out": 0,
    "light_out": 0,
    "curtain_status": "",
    "thresholds_status": "",
    "sensor_status": "",
    "timestamp": ""
}

A_PIN = [2, 3, 4, 5]
B_PIN = [6, 7, 8, 9]

HALF_STEP_SEQ = [
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [0, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 1, 1],
    [0, 0, 0, 1],
    [1, 0, 0, 1]
]

FILE = "THL measurement.csv"


class Motor:
    def __init__(self):
        """
        Initialize the Motor class.
        """
        self.A_pins = [Pin(i, Pin.OUT) for i in A_PIN]
        self.B_pins = [Pin(i, Pin.OUT) for i in B_PIN]
        self.seq = HALF_STEP_SEQ

    def step_motor(self, delay, steps, direction=1):
        """
        Control the stepper motor.
        :param delay: delay between steps
        :param steps: number of steps to move
        :param direction: the direction of movement, 1 for closing and -1 for opening
        """
        for _ in range(steps):
            for step in range(8):
                for Apin, Bpin, i in zip(self.A_pins, self.B_pins, range(4)):
                    Apin.value(self.seq[step][::direction][i])
                    Bpin.value(self.seq[step][::direction][3 - i])
                time.sleep(delay)


class SmartCurtain:
    def __init__(self, motor):
        """
        Initialize the SmartCurtain class.
        :param motor: Motor object of the curtain
        """
        # Initialize the pins
        self.thresholds = {}
        self.dht_indoor = dht.DHT22(Pin(DHT_PIN_IN))
        self.dht_outdoor = dht.DHT22(Pin(DHT_PIN_OUT))
        self.light_adc_indoor = ADC(LIGHT_PIN_IN)
        self.light_adc_outdoor = ADC(LIGHT_PIN_OUT)
        
        # Initialize measurable parameters
        self.curtain_status = CURRENT_CURTAIN_STATUS  # 0: open, 1: closed
        self.start_time = time.time()
        self._stop= False

        # Initialize thresholds
        self.load_thresholds()

        # Initialize the motor
        self.motor = motor

        # Initialize the file for data storage
        self.f = open(FILE, "w")
        header = "timestamp,temp_in,hum_in,light_in,temp_out,hum_out,light_out\n"
        self.f.write(header)
        
        self.status = DEFAULT_STATUS

    @staticmethod
    def read_lux(raw):
        """
        Convert the raw ADC value to lux using the formula:
        :param raw: light value from ADC
        :return: lux value
        """
        Vout = VOLTAGE * raw / ADC_MAX
        if Vout <= 0 or Vout >= VOLTAGE:
            return None
        Rldr = R_FIXED * Vout / (VOLTAGE - Vout)
        lux = 10.0 * math.pow(Rldr / R10, -1.0 / GAMMA)
        return lux

    def save_thresholds(self):
        """
        Save the current thresholds to a JSON file in Pico.
        """
        with open("thresholds.json", "w") as f:
            ujson.dump(self.thresholds, f)

    def load_thresholds(self):
        """
        Load thresholds from a JSON file in Pico.
        """
        try:
            with open("thresholds.json", "r") as f:
                self.thresholds = ujson.load(f)
        except Exception as e:
            self.status["thresholds_status"] = "Error loading thresholds: " + str(e)
            self.thresholds = DEFAULT_THRESHOLDS.copy()

    def order_get(self):
        """
        Get the order from stdin and update the order's dictionary:
        :return order for motor
        """
        order = 0
        priority = self.thresholds["priority"]
        if self.status[priority] > self.thresholds[priority] and self.curtain_status == 0:
            order = 1
            self.curtain_status = 1
            self.status["curtain_status"] = "Curtain Closed"
        elif self.status[priority] < self.thresholds[priority] and self.curtain_status == 1:
            order = -1
            self.curtain_status = 0
            self.status["curtain_status"] = "Curtain Opened"
        return order

    async def async_read_thresholds(self):
        """
        Read thresholds from stdin and update the thresholds' dictionary.
        """
        while not self._stop:
            if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                try:
                    line = sys.stdin.readline().strip()
                    data = ujson.loads(line)
                    self.thresholds.update(data)
                    self.save_thresholds()
                    self.status["thresholds_status"] = "Thresholds updated"
                except Exception as e:
                    self.status["thresholds_status"] = "Error updating thresholds: " + str(e)
            await asyncio.sleep(0.1)

    async def async_update_sensor(self):
        """
        Read data from the DHT sensor and update the status dictionary.
        """
        while not self._stop:
            elapsed = time.time() - self.start_time
            if elapsed >= TIME_TOTAL:
                # 超过两个小时，停止测量
                self._stop = True
                break
            
            try:
                t = time.localtime()
                ts = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(*t[:6])

                self.dht_indoor.measure()
                tin = self.dht_indoor.temperature()
                hin = self.dht_indoor.humidity()
                lin = self.read_lux(self.light_adc_indoor.read_u16()) or 0
                
                self.dht_outdoor.measure()
                tout = self.dht_outdoor.temperature()
                hout = self.dht_outdoor.humidity()
                lout = self.read_lux(self.light_adc_outdoor.read_u16()) or 0

                self.status.update({
                    "timestamp": ts,
                    "temperature_in": tin,
                    "humidity_in":    hin,
                    "light_in":       lin,
                    "temperature_out": tout,
                    "humidity_out":    hout,
                    "light_out":       lout,
                    "sensor_status": "Sensor working"
                })
                
                
                
                line = f"{ts},{tin},{hin},{lin},{tout},{hout},{lout}\n"
                self.f.write(line)

            except Exception as e:
                self.status["sensor_status"] = "Sensor error: " + str(e)

            print(ujson.dumps(self.status))
            await asyncio.sleep(TIME_INTERVAL)

    async def async_control_motor(self):
        """
        Control the motor based on thresholds.
        """
        while not self._stop:
            order = self.order_get()
            if order == 1:
                self.motor.step_motor(DEFAULT_DELAY, STEPS_UP, order)
            elif order == -1:
                self.motor.step_motor(DEFAULT_DELAY, STEPS_DOWN, order)
            await asyncio.sleep(1)

    async def run_all(self):
        """
        Main function to run all tasks concurrently.
        """
        await asyncio.gather(
            self.async_read_thresholds(),
            self.async_update_sensor(),
            self.async_control_motor()
        )


if __name__ == "__main__":
    motor = Motor()
    smart_curtain = SmartCurtain(motor)
    try:
        asyncio.run(smart_curtain.run_all())
    finally:
        smart_curtain.f.close()

