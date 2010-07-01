from isisobject import IsisObject

# Object generators used to instantiate various objects

class IsisObjectGenerator():
    def __init__(self, name, model, scale = 1, density = 2000, offsets = (0, 0, 0)):
        """ This defines a generator object from which instances are derived."""
        self.name = name
        self.model = model
        self.scale = scale
        self.density = density
        #TODO: Automatically center models once they are loaded
        self.offsets = offsets
   
    def generate_instance(self, physicalManager, pos = (0, 0, 0), parent = None):
        """ Generates a new object and adds it to the world"""
        model = loader.loadModel(self.model)
        model.setScale(self.scale)
        # flatten strong causes problem with physics
        #model.flattenLight()

        # add item to Isisworld
        obj = IsisObject(self.name, model, self.density)
        if parent:
            obj.reparentTo(parent)
        obj.setPos(pos)
        model.setPos(self.offsets[0]*obj.width, self.offsets[1]*obj.length, self.offsets[2]*obj.height)
        # add object to physical manager
        geom = physicalManager.addObject(obj)
        # and store its geometry
        obj.geom = geom

        #obj.update()

        return obj
