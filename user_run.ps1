if (-not (Test-Path .\venv))
{
    .\python\python.exe -m pip install virtualenv  
    .\python\python.exe -m virtualenv venv  
    
    . .\venv\Scripts\activate

    pip install -r requirements.txt
} else
{
    . .\venv\Scripts\activate
}

.\python\python.exe .\main.py .\res\NewWorld_Part_Ship_01.zen "C:/Program Files/Blender Foundation/Blender 4.2/blender.exe" "F:/Games/Gothic II" -o "C:/Users/Pttychka-Admin/Desktop/test.blend" -v 3

. .\venv\Scripts\deactivate
