import cv2 as cv
import numpy as np
from functions import *



img = cv.imread("Photos/park.jpg")
#cv.imshow("Color", img)


# Convert to Graysclale
gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
#cv.imshow("Gray", gray)

# Gaussian Blur
blur = cv.GaussianBlur(img, (7, 7), cv.BORDER_DEFAULT)
#cv.imshow("Blured", blur)

# Edge Cascade
canny = cv.Canny(blur, 125, 175)
#cv.imshow("Canny Edges", canny)

# Dilating the Image
dilated = cv.dilate(canny, (7,7), iterations=3)
#cv.imshow("Dilated", dilated)

# Eroding
eroded = cv.erode(dilated, (7,7), iterations=3)
#cv.imshow("Eroded", eroded)

# Resize
resized = cv.resize(img, (500,500), interpolation=cv.INTER_CUBIC)
cv.imshow("Resized", resized)

# Cropping
cropped = img[50:200, 200:400]
cv.imshow("Cropped", cropped) 


cv.waitKey(0)
cv.destroyAllWindows