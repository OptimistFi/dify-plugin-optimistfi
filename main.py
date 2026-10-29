from dify_plugin import DifyPluginEnv, Plugin

# The slowest OptimistFi views are computed on request; the client gives up at 100 seconds.
plugin = Plugin(DifyPluginEnv(MAX_REQUEST_TIMEOUT=120))

if __name__ == "__main__":
    plugin.run()
