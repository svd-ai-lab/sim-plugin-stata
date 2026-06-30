* Minimal Stata fixture for sim-plugin-stata.
* Loads a bundled dataset, runs a quick summary, and emits a single JSON
* line as the LAST {-prefixed line so parse_output() can pick it up.
*
* JSON in Stata: use COMPOUND double quotes  `"..."'  so literal " survive
* (a plain "" inside "..." is NOT an escaped quote in Stata — it ends the
* string), and interpolate numeric values through local macros.
clear all
set more off
sysuse auto, clear
quietly count
local n = r(N)
quietly summarize price
local mean = r(mean)
display `"{"status":"ok","obs":`n',"mean_price":`mean'}"'
