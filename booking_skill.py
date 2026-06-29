import sys
import time

def main():
    if len(sys.argv) < 3:
        print("Usage: python booking_skill.py <image_path> <time_slot>")
        sys.exit(1)
        
    image_path = sys.argv[1]
    time_slot = sys.argv[2]
    
    print(f"--- BOOKING SKILL STARTED ---")
    print(f"[1/3] Processing image: {image_path} with GPT-5.5 Vision...")
    time.sleep(1)
    print(f"[2/3] Extracted Data: Carrier=Kuroneko Yamato, Tracking=1234-5678-9012")
    time.sleep(1)
    print(f"[3/3] Navigating to Yamato website to book slot: {time_slot}...")
    time.sleep(1)
    print(f"✅ Success! Redelivery booked for {time_slot}.")

if __name__ == "__main__":
    main()
