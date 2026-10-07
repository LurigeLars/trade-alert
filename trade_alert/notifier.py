from __future__ import annotations

import base64
import html
import os
import subprocess


def _encoded_powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def notify(title: str, body: str) -> None:
    if os.name != "nt":
        print(f"[{title}] {body}")
        return

    safe_title = html.escape(title, quote=False)
    safe_body = html.escape(body, quote=False)
    xml = (
        "<toast><visual><binding template='ToastGeneric'>"
        f"<text>{safe_title}</text><text>{safe_body}</text>"
        "</binding></visual></toast>"
    )
    script = rf'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
{xml}
'@)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Trade Alert').Show($toast)
'''
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", _encoded_powershell(script)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
