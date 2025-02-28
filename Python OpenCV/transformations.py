import cv2 as cv
from functions import *

img = cv.imread("Photos/park.jpg")
cv.imshow("Boston", img)


# Translated Image
translated_img = translate(img, 100, -100)
cv.imshow("Boston Translated", translated_img)


# Rotated Image
rotated = rotate(img, 45)
cv.imshow("Boston Rotated", rotated)


# Resized Image
resized = cv.resize(img, (500,500), interpolation=cv.INTER_AREA)
cv.imshow("Boston Resized", resized)


# Flipping Image
flip = cv.flip(img, 0)
cv.imshow("Flipped Boston", flip)

''' FlipCode:
0 --> Vertical Mirror
1 --> Horaizontal Mirror
-1 --> Both Horizontal and Vertical Mirror
'''

# Cropping Image
cropped = img[200:400, 300:400]
cv.imshow("Boston Cropped", cropped)


cv.waitKey(0)
cv.destroyAllWindows()