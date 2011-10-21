from direct.showbase.ShowBase import ShowBase
from panda3d.core import loadPrcFileData#@UnresolvedImport
from panda3d.core import NodePath, Point2, Point3, VBase4, GeomNode#@UnresolvedImport
from panda3d.core import ShadeModelAttrib, DirectionalLight, AmbientLight#@UnresolvedImport
from pandac.PandaModules import CollisionTraverser, CollisionHandlerQueue, CollisionNode, CollisionRay#@UnresolvedImport
from direct.interval.IntervalGlobal import Sequence, ActorInterval, Parallel, Func
from camera import Camera
from interface import Interface
from unitmodel import UnitModel
import sys
import logging
import cPickle as pickle
from messaging import ClientMsg, Msg

#===============================================================================
# Panda3D parameter file handling
#===============================================================================

loadPrcFileData("", "model-path "+"$MAIN_DIR/models")
loadPrcFileData("", "model-path "+"$MAIN_DIR/sounds")
loadPrcFileData("", "model-path "+"$MAIN_DIR/textures")

# config dictionary variable
config = {} 
cfile = open("etc/user.cfg", "r")
while 1:
    string = cfile.readline()
    if (string == ""):
        break
    elif (string[0] == "#"):
        continue
    part = string.rsplit("=")
    config[part[0].strip()] = part[1].strip()
cfile.close()

loadPrcFileData("", "fullscreen "+config["fullscreen"])
loadPrcFileData("", "win-size "+config['resx']+" "+config["resy"])
loadPrcFileData("", "show-frame-rate-meter "+config["showfps"])
loadPrcFileData("", "model-cache-dir ./tmp")
loadPrcFileData("", "window-title Strain")
if config["scene-explorer"] == "1":
    loadPrcFileData("", "want-directtools #t")
    loadPrcFileData("", "want-tk #t")


#===============================================================================
# SET UP LOGGING
#===============================================================================
logger = logging.getLogger('GraphicsLog')
hdlr = logging.FileHandler('Graphics.log')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
logger.addHandler(hdlr) 
logger.setLevel(logging.DEBUG)


#===============================================================================
# CLASS GraphicsEngine --- DEFINITION
#===============================================================================
class GraphicsEngine(ShowBase):
    """Class implementing graphics engine. Inherits from Panda3d ShowBase class. 
       Handles scene graph objects and runs a main draw loop.
    """
    
    def __init__(self):
        """Initializes all components of scene graph and Panda3d ShowBase class which creates window for us."""
        
        logger.info("---------------------GraphicsEngine Starting------------------------")
        ShowBase.__init__(self)
        #PStatClient.connect()

        self.engineLoaded = False

        # Create messaging task
        self.taskMgr.add(self.msgTask, "msg_task")
        
        # Get engine state (initializes players, units, levels)
        ClientMsg.getEngineState()
        
        # Main node in a scene graph. Everything should be reparented to this node or another node under this node
        # This node is reparented to render
        self.node = self.render.attachNewNode("master")
        
        # Disable default Panda3d camera implementation
        self.disableMouse()

        self.accept("window-event", self.windowEvent)
        self.accept("escape", self.destroy)
        self.accept('aspectRatioChanged', self.redraw)        
        
        # global flag to disable user interface (when animations are playing etc)
        self.interface_disabled = False
        
        # debug
        self.accept("i", self.info)

    def initAll(self, level, players, units):
        """Initializes all the components of scene graph."""
        # TODO: ogs: Napraviti proceduru i za deinicijalizaciju svega i testirati kroz pstats
        self.initLevel(level)
        self.initUnits(players, units)
        self.initLights()
        self.initAltBuffer()
        self.initCollision()  
        # Initialize custom app camera implementation
        self.app_camera = Camera(self.camera, self.mouseWatcherNode, self.level.maxX, self.level.maxY) 
        # Initialize graphical user interface elements
        self.interface = Interface(self)  
        
        # Create unit anim task
        self.taskMgr.add(self.animTask, "anim_task")        
    
    def initLevel(self, level):
        # Main level node in a scene graph
        self.level_node = self.node.attachNewNode("levelnode")
        # List to store nodepaths of all tiles in a level
        self.tile_np_list = []
        # List to store nodepaths of all units
        # List indices equal level coordinates
        # Empty coordinates are stored as None values
        # Here we just allocate the list and fill it with None values
        self.unit_np_list = [[None] * level.maxX for i in xrange(level.maxY)]
        for x in xrange(0, level.maxX): 
            tile_nodes = []
            for y in xrange(0, level.maxY): 
                tag = level._level_data[x][y]
                c = self.loader.loadModel("tile")
                if tag != 0:
                    c.setScale(1, 1, tag + 1)
                    #TODO: ogs: Srediti ovaj colorScale, izgleda da ne radi dobro s ovom teksturom
                    coef = 1 + 0.05 * tag
                    c.setColorScale(coef, coef, coef, 1)
                    c.flattenLight()
                c.setPos(x, y, 0)
                c.setTag("pos", "%(X)s-%(Y)s" % {"X":x, "Y":y})
                c.setTag("type", "tile")                     
                c.reparentTo(self.level_node)
                tile_nodes.append(c)
            self.tile_np_list.append(tile_nodes)

    def initUnits(self, players, units):
        # Set up dictionaries for player and unit nodepaths
        self.player_np_dict = {}
        self.unit_np_dict = {}
        
        for player in players:
            # Create a node in the scene graph for each player
            player_node = self.node.attachNewNode(str(player.id) + "_playernode")
            self.player_np_dict[player.id] = player_node 
            
        for unit in units.itervalues():
            um = UnitModel(unit)
            um.node.reparentTo(self.node)
            # Keep unit nodepath in dictionary of all unit nodepaths
            self.unit_np_dict[unit.id] = um
            # Keep unit nodepath in list corresponding to level size
            # This will be dinamically altered when units change position
            self.unit_np_list[unit.x][unit.y] = um

    def initLights(self):
        shade = ShadeModelAttrib.make(ShadeModelAttrib.MSmooth)
        self.render.setAttrib(shade)
        dlight1 = DirectionalLight("dlight1")
        dlight1.setColor(VBase4(1.0, 1.0, 1.0, 1.0))
        dlnp1 = self.render.attachNewNode(dlight1)
        dlnp1.setHpr(-10, -30, 0)
        self.render.setLight(dlnp1)
        alight = AmbientLight("alight")
        alight.setColor(VBase4(0.3, 0.3, 0.3, 1.0))
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)

    def initAltBuffer(self):
        """Initializes off screen buffer used to render models and animations for unit portraits."""
        self.alt_buffer = self.win.makeTextureBuffer("texbuf", 256, 256)
        self.alt_render = NodePath("offrender")
        self.alt_cam = self.makeCamera(self.alt_buffer)
        self.alt_cam.reparentTo(self.alt_render)        
        self.alt_cam.setPos(0,-10,0)
        self.alt_render.setLightOff()
        self.alt_render.setFogOff()

    def initCollision(self):
        """Initializes objects needed to perform panda collisions."""
        self.coll_trav = CollisionTraverser()
        self.coll_queue = CollisionHandlerQueue()
        self.coll_node = CollisionNode("mouse_ray")
        self.coll_nodepath = self.camera.attachNewNode(self.coll_node)
        self.coll_node.setFromCollideMask(GeomNode.getDefaultCollideMask())
        self.coll_ray = CollisionRay()
        self.coll_node.addSolid(self.coll_ray)
        self.coll_trav.addCollider(self.coll_nodepath, self.coll_queue)

    def destroyUnit(self, unit):
        """Removes unit nodepath from scenegraph. It will eventually be collected by reference-counting mechanism and destroyed."""
        unit.cleanup()
        unit.remove()
        
    def updateUnit(self, unit):
        self.unit_np_dict[unit.id].unit = unit
    
    def windowEvent(self, win):
        if win.isClosed():
            self.destroy()

    def redraw(self):
        pass
        
    def info(self):
        #print render.ls()
        print self.render.analyze()
        
    def destroy(self):
        # TODO: ogs: Nekad se na izlazu javlja:debug('feeder thread got sentinel -- exiting') - vjerovatno vezano uz threading, provjeriti
        if self.interface.selected_unit:
            self.interface.deselectUnit()
        else:
            ClientMsg.shutdownEngine()          
            ClientMsg.close()  
            sys.exit()

    def setInterfaceEnable(self):
        self.interface_disabled = False
        
    def setInterfaceDisable(self):
        self.interface_disabled = True
            
    def getUnitData(self, unit, type):
        if type == "type":
            return unit.unit.type
        elif type == "HP":
            return unit.unit.health
        elif type == "AP":
            return unit.unit.current_AP
        elif type == "default_HP":
            return unit.unit.default_HP
        elif type == "default_AP":
            return unit.unit.default_AP
    
    def setUnitNpList(self, unit, old_pos):
        pos = unit.model.getPos()
        self.unit_np_list[int(old_pos.getX())][int(old_pos.getY())] = None
        self.unit_np_list[int(pos.getX())][int(pos.getY())] = unit

    def playUnitAnim(self, unit, action_list):
        intervals = []
        duration = 0.0
        start_pos = unit.model.getPos()
        # if legth of action list is greater than 1, we have movement and rotation information
        if len(action_list) > 1:
            end_pos = action_list[-2][1]
        # otherwise, we are just rotating the unit so end_pos is the same as unit pos
        else:
            end_pos = Point2(int(unit.model.getX()), int(unit.model.getY()))
        for idx, action in enumerate(action_list):
            type = action[0]
            if idx == 0:
                curr_pos = start_pos
                curr_h = unit.model.getH()
            else:
                curr_pos = dest_pos
                curr_h = dest_h
                
            dest_pos = Point3(action[1].getX() + 0.5, action[1].getY() + 0.5, 0.3)
            if type == "move":
                unit.dummy_node.setPos(curr_pos)
                unit.dest_node.setPos(dest_pos)
                unit.dummy_node.lookAt(unit.dest_node)
                dest_h = unit.dummy_node.getH()
                # Model heading is different than movement heading, first create animation that turns model to his destination
                i_h = None
                if dest_h != curr_h:
                    i_h = unit.model.quatInterval(0.2, hpr = Point3(dest_h, 0, 0), startHpr = Point3(curr_h, 0, 0))
                    curr_h = dest_h
                i = unit.model.posInterval(0.5, dest_pos, curr_pos)
                duration = duration + 0.5
                if i_h:
                    p = Parallel(i, i_h)
                else:
                    p = i
                intervals.append(p)
            elif type == "rotate":
                unit.dummy_node.setPos(curr_pos)
                unit.dest_node.setPos(dest_pos)
                unit.dummy_node.lookAt(unit.dest_node)
                dest_h = unit.dummy_node.getH() 
                i_h = unit.model.quatInterval(0.2, hpr = Point3(dest_h, 0, 0), startHpr = Point3(curr_h, 0, 0))
                duration = duration + 0.2
                intervals.append(i_h)                 
        seq = Sequence()
        for i in intervals:
            seq.append(i)
        #return
        anim = ActorInterval(unit.model, 'run', loop = 1, duration = duration)
        move = Sequence(Parallel(anim, seq), 
                        Func(self.setUnitNpList, self.unit_np_dict[int(unit.id)], start_pos),
                        Func(self.interface.markSelectedTile, self.tile_np_list[int(end_pos.getX())][int(end_pos.getY())]),
                        #Func(self.interface.printUnitData, unit)
                        )
        move.start()

    # TODO: ogs: maknuti ove pozive i zvati direktno messaging.py
    def createMoveMsg(self, unit, pos, orientation):
        ClientMsg.move(int(unit.id), pos, orientation)
        
    def createEndTurnMsg(self):
        ClientMsg.endTurn()
           
    def handleMsg(self, msg):
        """Handles incoming messages."""
        logger.info("Received message: %s", msg.type)
        if msg.type == Msg.ENGINE_STATE:
            self.level = pickle.loads(msg.values['pickled_level'])
            self.turn = msg.values['turn']
            players = pickle.loads(msg.values['pickled_players'])            
            units = pickle.loads(msg.values['pickled_units'])
            self.initAll(self.level, players, units)
            if not self.engineLoaded:
                self.engineLoaded = True
        elif msg.type == Msg.MOVE:
            unit_id = msg.values[0]
            tile_list = msg.values[1]
            unit = self.unit_np_dict[unit_id]
            self.interface.clearSelectedTile(self.tile_np_list[int(unit.model.getX())][int(unit.model.getY())])
            self.playUnitAnim(self.unit_np_dict[unit_id], tile_list)
        elif msg.type == Msg.NEW_TURN:
            print msg.values
        elif msg.type == Msg.UNIT:
            if self.engineLoaded:
                unit = pickle.loads(msg.values)
                self.updateUnit(unit)
                self.interface.printUnitData()
        # TODO: ogs: implementirati primanje ostalih poruka
        else:
            logger.error("Unknown message Type: %s", msg.type)

    def msgTask(self, task):
        """Task that listens for messages on client queue."""
        msg = ClientMsg.readMsg()        
        if msg:
            self.handleMsg(msg)            
        return task.cont
    
    def animTask(self, task):
        """Task to animate draw units while they are idling."""
        dt = globalClock.getDt()
        for unit in self.unit_np_dict.itervalues():
            unit.passtime += dt

            if unit.passtime > unit.idletime:
                anim = unit.getAnimName("idle")
                unit.model.play(anim)
                unit.passtime = 0
                unit.setIdleTime()
            
        return task.cont
    