import pandas as pd
import matplotlib.pyplot as plt

# List of Usefull Paths
CSV_PATH   = "C:/Users/gonca/Desktop/Collisions DEM/Collision-Study/disk_tracks.csv"
EXCEL_PATH = "disk_tracks_by_color.xlsx"
PLOT_PATH  = "trajectories.png"

# id -> color mapping (green=0, blue=1)
ID_TO_COLOR = {0: "green", 1: "blue"}

# Load CSV
df = pd.read_csv(
    CSV_PATH,
    dtype={"frame": "int32", "disk_id": "int8"},
    na_values=["", "None"]
).sort_values(["disk_id", "frame"])

df["color"] = df["disk_id"].map(ID_TO_COLOR)

# Convert to Excel 
with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as writer:
    df[df["disk_id"] == 0].to_excel(writer, sheet_name="green", index=False)
    df[df["disk_id"] == 1].to_excel(writer, sheet_name="blue",  index=False)
print(f"[Done] Excel written to {EXCEL_PATH}")

# Make a ScatterPlot
plt.figure(figsize=(7, 7))

g = df[df["disk_id"] == 0].dropna(subset=["cx_mm", "cy_mm"])
b = df[df["disk_id"] == 1].dropna(subset=["cx_mm", "cy_mm"])

plt.scatter(
    g["cx_mm"], g["cy_mm"],
    color="green", label="green disk", s=15   # s = marker size
)
plt.scatter(
    b["cx_mm"], b["cy_mm"],
    color="blue", label="blue disk", s=15
)

plt.xlabel("x (mm)")
plt.ylabel("y (mm)")
plt.title("Disks Trajectories (ScatterPlot)")
plt.legend()
plt.axis("equal")

plt.gca().invert_yaxis()
plt.tight_layout()
plt.savefig(PLOT_PATH, dpi=150)
print(f"[Done] Plot saved to {PLOT_PATH}")

# Show in an interactive window too
plt.show()
