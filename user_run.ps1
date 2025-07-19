if (-not (Test-Path .\.venv))
{
    .\python\python.exe -m pip install virtualenv  
    .\python\python.exe -m virtualenv .venv  
    
    . .\venv\Scripts\activate

    pip install -r requirements.txt
} else
{
    . .\venv\Scripts\activate
}

.\python\python.exe .\main.py -c .\config.json -v 2

. .\venv\Scripts\deactivate
