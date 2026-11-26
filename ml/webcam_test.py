
import cv2

def test_webcam():

    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        print("ERROR: Webcam not detected!")
        return

    print("Webcam started successfully!")
    print("Press Q to close the camera.")

    while True:

        success, frame = camera.read()

        if not success:
            print("Unable to capture frame.")
            break

        cv2.imshow("Smart Voting - Webcam Test", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    camera.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    test_webcam()
