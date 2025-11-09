# Phosaic

Create your own Jumpbotron on the fly!

## Running

This has not been tested on Window or Mac, so if you are attempting to run it there good luck.

Clone the repository and run `bash node server/server.js`

Run `bash python3 coordinator/interface.py`

Connect any devices you want to act as subordinates to the webserver.

On the coordinator interface select either screen capture (X11) or video (Anything else). If using a video upload a video from your local file system.

Select the camera you are using on the left panel and turn it on.

Then tap the screen of each subordinate to get the QR code display.

Place the devices within view of camera, and TADA!
