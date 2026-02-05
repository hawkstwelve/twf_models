# TWF HRRR V2 Scheduler (systemd)

## Install

```
sudo cp deployment/systemd/twf-hrrr-v2-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now twf-hrrr-v2-scheduler
sudo systemctl status twf-hrrr-v2-scheduler --no-pager
sudo journalctl -u twf-hrrr-v2-scheduler -f
```
