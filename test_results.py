import pandas as pd

# CSV reader
df = pd.read_csv("disk_tracks.csv")

# Subsets Green == 0 and Blue == 1
df_green = df[df["disk_id"]] == 0
df_blue = df[df["disk_id"]] == 1



# Linear Moment

