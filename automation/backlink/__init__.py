"""
automation.backlink package.

Generate Backlinks (ping submission) automation.

Flow (per requirement):
  read ping sites one by one ->
  open N sessions in parallel (sessions.parallel, default 5) ->
  submit first 5 targets, next 5, ... in batches ->
  wait for each site to finish -> log to DB ->
  close sessions -> continue next batch / next site.
"""
