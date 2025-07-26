if (-not (Test-Path .\venv))
{
    .\python\python.exe -m pip install virtualenv  
    .\python\python.exe -m virtualenv venv  
    
    . .\venv\Scripts\activate

    pip install git+https://github.com/Zira3l137/ZenKit4Py.git 
    
} else
{
    . .\venv\Scripts\activate
}

.\python\python.exe .\main.py "F:\Games\Gothic II\_work\data\Worlds\NewWorld\NewWorld_Part_Xardas_01.zen" "C:/Program Files/Blender Foundation/Blender 4.2/blender.exe" "F:\Games\Gothic II" -o "C:/Users/Pttychka-Admin/Desktop/test.blend" -w -v 3

. .\venv\Scripts\deactivate
