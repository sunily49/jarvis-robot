"""
JARVIS Hardware Test Script — run on Pi to verify all hardware.

Usage: python3 scripts/test_hardware.py
"""

import sys
import time


def test_camera():
    """Test camera capture."""
    print("\n[Camera]")
    try:
        import cv2
        for dev in ["/dev/video0", "/dev/video1", 0, 1]:
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                ret, frame = cap.read()
                cap.release()
                if ret:
                    print(f"  ✓ Camera OK — {dev}, frame: {frame.shape}")
                    return True
                print(f"  ✗ Camera opened at {dev} but no frame")
            else:
                cap.release()
        print("  ✗ Camera not found at /dev/video0 or /dev/video1")
        return False
    except ImportError:
        print("  ✗ opencv not installed")
        return False


def test_microphone():
    """Test audio capture."""
    print("\n[Microphone]")
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        info = pa.get_default_input_device_info()
        print(f"  ✓ Default input: {info['name']} (index={info['index']})")
        count = pa.get_device_count()
        for i in range(count):
            dev = pa.get_device_info_by_index(i)
            if dev['maxInputChannels'] > 0:
                print(f"    Input device {i}: {dev['name']}")
        pa.terminate()
        return True
    except Exception as e:
        print(f"  ✗ Microphone error: {e}")
        return False


def test_speaker():
    """Test audio output."""
    print("\n[Speaker]")
    try:
        import subprocess
        result = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = [l for l in result.stdout.split("\n") if "card" in l.lower()]
            for line in lines:
                print(f"  Output: {line.strip()}")
            print("  ✓ Speaker devices found")
            return True
        print("  ✗ No audio output devices")
        return False
    except Exception as e:
        print(f"  ✗ Speaker test error: {e}")
        return False


def test_gpio():
    """Test GPIO availability."""
    print("\n[GPIO]")
    try:
        import RPi.GPIO as GPIO
        info = GPIO.RPI_INFO
        print(f"  ✓ GPIO OK — Pi {info.get('TYPE', 'unknown')}, Rev {info.get('REVISION', '?')}")
        GPIO.setmode(GPIO.BCM)
        GPIO.cleanup()
        return True
    except ImportError:
        print("  ✗ RPi.GPIO not installed (not on Pi?)")
        return False
    except Exception as e:
        print(f"  ✗ GPIO error: {e}")
        return False


def test_i2c():
    """Test I2C bus (for PCA9685 servo board)."""
    print("\n[I2C]")
    try:
        import subprocess
        result = subprocess.run(["i2cdetect", "-y", "1"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            # Check for any devices
            found = [c for line in result.stdout.split("\n") for c in line.split() if c not in ("--", "") and not c.endswith(":")]
            if found:
                print(f"  ✓ I2C devices found at: {', '.join(found)}")
            else:
                print("  ○ I2C bus OK but no devices detected")
            return True
        print("  ✗ i2cdetect failed")
        return False
    except FileNotFoundError:
        print("  ✗ i2cdetect not found — install: sudo apt install i2c-tools")
        return False
    except Exception as e:
        print(f"  ✗ I2C error: {e}")
        return False


def test_network():
    """Test network connectivity."""
    print("\n[Network]")
    try:
        import socket
        s = socket.create_connection(("8.8.8.8", 53), timeout=5)
        s.close()
        print("  ✓ Internet OK")

        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        print(f"  ✓ Hostname: {hostname}, IP: {ip}")
        return True
    except Exception as e:
        print(f"  ✗ Network error: {e}")
        return False


def test_v4l2():
    """Test v4l2 PTZ control."""
    print("\n[PTZ Camera (v4l2)]")
    try:
        import subprocess
        result = subprocess.run(
            ["v4l2-ctl", "--list-devices"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            print(f"  ✓ v4l2 devices:\n    " + result.stdout.replace("\n", "\n    "))
            return True
        print("  ✗ No v4l2 devices")
        return False
    except FileNotFoundError:
        print("  ✗ v4l2-ctl not found — install: sudo apt install v4l-utils")
        return False


def main():
    print("=" * 50)
    print("  JARVIS Hardware Diagnostic")
    print("=" * 50)

    tests = [
        test_camera,
        test_microphone,
        test_speaker,
        test_gpio,
        test_i2c,
        test_network,
        test_v4l2,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            results.append(False)

    passed = sum(1 for r in results if r)
    total = len(results)

    print("\n" + "=" * 50)
    print(f"  Results: {passed}/{total} passed")
    print("=" * 50)

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
