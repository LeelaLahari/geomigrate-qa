def classFactory(iface):
    from .plugin import GeoMigratePlugin
    return GeoMigratePlugin(iface)