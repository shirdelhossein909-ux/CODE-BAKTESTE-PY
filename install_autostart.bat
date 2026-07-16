@echo off
chcp 65001 >nul
echo Registering the robot to start automatically after every Windows logon...
schtasks /Create /TN "ZoneTradingRobot" /TR "\"%~dp0start_robot.bat\"" /SC ONLOGON /RL HIGHEST /F
if %errorlevel%==0 (
    echo.
    echo DONE. The robot will start automatically after every Windows restart/logon.
    echo To remove later:  schtasks /Delete /TN "ZoneTradingRobot" /F
) else (
    echo.
    echo FAILED. Right-click this file and choose "Run as administrator".
)
pause
