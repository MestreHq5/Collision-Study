import cv2 as cv
from functions import *
import numpy as np


img = cv.imread("Python OpenCV\Test Imaging\One_BD.jpg")
scaled = rescaleFrame(img, 0.20)
#cv.imshow("Scaled Original", scaled)

blank = np.zeros(scaled.shape, dtype='uint8')
#cv.imshow("Blank", blank)

gray = cv.cvtColor(scaled, cv.COLOR_BGR2GRAY)
#cv.imshow('GreyScale Blue Disk', gray)

blur = cv.GaussianBlur(gray, (5,5), cv.BORDER_DEFAULT)
cv.imshow("Blured Image", blur)

canny = cv.Canny(blur, 125, 175)
#cv.imshow("Canny Edges", canny)

ret, thresh = cv.threshold(gray, 125, 255, cv.THRESH_BINARY)

contours, hierarchy = cv.findContours(canny, cv.RETR_LIST, cv.CHAIN_APPROX_NONE)
print(len(contours))

cv.drawContours(blank, contours, -1, (0,0,255), 1)
cv.imshow("Contours", blank)


cv.waitKey(0)
cv.destroyAllWindows