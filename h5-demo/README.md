# H5 Demo

## Start backend

```bash
cd /Users/terrixchan/Library/CloudStorage/OneDrive-个人/code/maptoposter
pip install -r wx_service/requirements.txt
uvicorn wx_service.app:app --host 0.0.0.0 --port 8000
```

## Open H5 page

Any static server works, for example:

```bash
cd /Users/terrixchan/Library/CloudStorage/OneDrive-个人/code/maptoposter/h5-demo
python3 -m http.server 5173
```

Then open [http://127.0.0.1:5173](http://127.0.0.1:5173).
