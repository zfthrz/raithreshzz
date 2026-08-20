# H5.4 Coaching Precision — P6 v0.2

Driver-facing Entry/Apex/Exit anchor selection.

- braking_onset -> entry only
- brake_release -> nearest of apex or exit
- throttle_onset -> nearest of apex or exit
- throttle_release -> nearest of entry or apex

Preserves event_distance_m and P4/P5 authority.
v0.2 includes the magnitude fix missing from v0.1.
