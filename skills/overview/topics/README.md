# Overview topics

Topic configs are USER data, not plugin code. The loader looks in
`~/.config/research-cards/topics/<key>/` first (each subdir with a
`config.py` becomes an available topic; `topic_snapshot.json` sits next to
it, maintained by `topology.py refresh`). This in-repo dir only ships the
`_example/` template — copy it out, rename, fill in, then register the
topic's hub in config `*.graph.hubs` so topology can derive the snapshot.
