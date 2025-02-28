import cv2 as cv
from functions import *
import numpy as np
from math import sqrt, ceil, floor, cos, sin, pi


# Black Board
blank = np.zeros((500, 500, 3),dtype='uint8')
center_cord = 250
size = 500


# White section
blank[150:350, 150:350] = 255, 255, 255

# Circle
radius = ceil(sqrt(100**2 + 100**2))
cv.circle(blank, (center_cord, center_cord), radius, (255,255,255), thickness=-1)

# Rectangles
for iter in range(100):
    cv.rectangle(blank, (center_cord, center_cord), (center_cord + ((-1)**iter)*iter, center_cord + ((-1)**iter)*iter), (0, 0, 0), thickness=1)

for iter2 in range(50):
    cv.rectangle(blank, (center_cord, center_cord), (center_cord + ((-1)**iter2)*2*iter2, center_cord - ((-1)**iter2)*2*iter2), (0, 0, 0), thickness=1)


# Lines Parametric
theta = 0
excentricity = 2
rad_spiral = 0

while rad_spiral <= radius:  
    rad_spiral = excentricity * theta 
    x = int(center_cord + rad_spiral * cos(theta))  
    y = int(center_cord + rad_spiral * sin(theta))  
    
    cv.circle(blank, (x, y), 1, (0, 0, 255), thickness=-1)
    theta += 2 * pi / 1000


# Text
text = "Drawing"
avg_size = 22
cv.putText(blank, text, (center_cord- avg_size*int(len(text)/2), center_cord - 200), cv.FONT_HERSHEY_TRIPLEX, 1.0, (255,255,255), 1)


cv.imshow("Final", blank)

cv.waitKey(0)


