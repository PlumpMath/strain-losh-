from xml.dom import minidom
import unit
from level import Level
import math
from server_messaging import *
from threading import Thread
import time
import logging
import logging.handlers
import sys, traceback
import cPickle as pickle
import util
from player import Player


notify = util.Notify()




DYNAMICS_EMPTY = 0
DYNAMICS_UNIT = 1


class Engine( Thread ):
    
        
    __index_uid = 0

    def getUID(self):
        Engine.__index_uid += 1
        return Engine.__index_uid -1
    

        
    #====================================init======================================0
    def __init__(self):
        Thread.__init__(self)
        notify.info("------------------------Engine Starting------------------------")

        self.stop = False
        self.level = None 
        self.dynamic_obstacles = []
        self.turn = 0        
        self.players = {}
        self.units = {}
        
        self.name = "EngineThread"


    def run(self):
        engine._instance = self
        print "Engine started"
        EngMsg.startServer( notify )
        
        lvl = "level2.txt"
        self.level = Level( lvl )
        notify.info("Loaded level:%s", lvl )

        #we make this so its size is the same as level 
        self.dynamic_obstacles = [[(0,0)] * self.level.maxY for i in xrange(self.level.maxX)] #@UnusedVariable
        
        self.loadArmyList()

        
        self.turn = 0        
        self.beginTurn()


        #+++++++++++++++++++++++++++++++++++++++++++++MAIN LOOP+++++++++++++++++++++++++++++++++++++++++++++
        #+++++++++++++++++++++++++++++++++++++++++++++MAIN LOOP+++++++++++++++++++++++++++++++++++++++++++++
        while( self.stop == False ):

            time.sleep( 0.1 )

            #see if there is a new client connected
            EngMsg.handleConnections()

            #get a message if there is one
            msg = EngMsg.readMsg()
            if msg:
                self.handleMsg( msg[0], msg[1] )
        
        #+++++++++++++++++++++++++++++++++++++++++++++MAIN LOOP+++++++++++++++++++++++++++++++++++++++++++++
        #+++++++++++++++++++++++++++++++++++++++++++++MAIN LOOP+++++++++++++++++++++++++++++++++++++++++++++
        
        #we are shutting down everything   
        EngMsg.stopServer()       
        
        notify.info( "++++++++++++++++++++++++Engine stopped!++++++++++++++++++++++++" ) 

        return 0


    def handleMsg(self, msg, source):
        """This method is the main method for handling incoming messages to the Engine"""     
        
        if( msg[0] == ENGINE_SHUTDOWN ):
            EngMsg.sendErrorMsg("Server is shutting down")
            self.stop = True
            
        elif( msg[0] == MOVE ):            
            self.moveUnit( msg[1]['unit_id'], msg[1]['new_position'], msg[1]['orientation'], source )
            
        elif( msg[0] == LEVEL ):                
            EngMsg.sendLevel( util.compileLevel( self.level ) )
                        
        elif( msg[0] == ENGINE_STATE ):                
            EngMsg.sendState( util.compileState( self ), source )
            
        elif( msg[0] == END_TURN ):
            self.endTurn()
                        
        elif( msg[0] == SHOOT ):
            self.shoot( msg[1]['shooter_id'], msg[1]['target_id'], source )
                        
        else:
            notify.error( "Unknown message Type: %s", msg )
        
        
                
    def loadArmyList(self):
        
        notify.debug( "Army lists loading" )
        
        xmldoc = minidom.parse('data/base/armylist.xml')
        #print xmldoc.firstChild.toxml()
        
        self.players = {}
        self.units = {}
        
        
        for p in xmldoc.getElementsByTagName( 'player' ):
            player = Player( p.attributes['id'].value, p.attributes['name'].value, p.attributes['team'].value )                        
            
            for u in p.getElementsByTagName( 'unit' ):
                
                x = int( u.attributes['x'].value )
                y = int( u.attributes['y'].value )
                
                unittype = u.attributes['type'].value
                
                #check to see level boundaries
                if( self.outOfLevelBounds(x, y) ):
                    print "This unit is out of level bounds", unittype, x, y
                    continue
                
                #check to see if there is something in the way on level
                if self.level._level_data[x][y] != 0:
                    print "This unit cannot be placed on non empty level tile", unittype, x, y
                    continue
                
                #check to see if the tile is already occupied
                if( self.dynamic_obstacles[x][y][0] != DYNAMICS_EMPTY ):
                    print "This tile already occupied, unit cannot deploy here", x, y, unittype
                    continue
                 
                tmpUnit = unit.loadUnit(unittype)
                
                tmpUnit.init( self.getUID(), player, x, y )                
                tmpUnit.heading = util.getHeading(tmpUnit.pos, self.level.center)
                
                player.unitlist.append( tmpUnit )
                self.units[tmpUnit.id] = tmpUnit
                
                self.dynamic_obstacles[x][y] = ( DYNAMICS_UNIT, tmpUnit.id )
                
            self.players[player.id] = player
    
        xmldoc.unlink()   

        notify.info( "Army lists loaded OK" )


    def endTurn(self):
        
        self.beginTurn()
        
        pass


    def beginTurn(self):
        
        
        #increment turn by one
        self.turn += 1

        EngMsg.sendNewTurn( self.turn )
        
        #go through all units
        for unit_id in self.units:
            
            unit = self.units[unit_id]
            
            #replenish AP
            unit.ap = unit.default_ap
            
            #if unit rested last turn
            if unit.resting:
                unit.ap += 1
                unit.resting = False
                
            
            #get new move_dict
            unit.move_dict = self.getMoveDict(unit)
            unit.losh_dict = self.getLOSHDict(unit.pos)
            

            #after updating everything send unit_id data to client        
            EngMsg.sendUnit( util.compileUnit(unit) )
        
        #check visibility
        self.checkVisibility()
        
        
    def checkVisibility(self):
        #TODO: krav: mozda stavit da se ide prvo po playerima?
        for player in self.players.itervalues():
            player.list_visible_enemies = []
            for myunit in player.unitlist:
                for enemy in self.units.itervalues():
                    if enemy.owner == player:
                        continue
                    if enemy.pos in myunit.losh_dict:
                        if enemy not in player.list_visible_enemies: 
                            player.list_visible_enemies.append( enemy )
                            print player.name,"\tvidim:", enemy.name, "\t@:", enemy.pos
        
        pass

    def outOfLevelBounds( self, x, y ):
        if( x < 0 or y < 0 or x >= self.level.maxX or y >= self.level.maxY ):
            return True
        else: 
            return False
        
    

    def getLOS(self, origin, target ):
        """this method returns list of tuples( (x,y, visibility ); visibility = {0:clear, 1:partial, 2:not visible}"""    
        x1 = origin[0]
        y1 = origin[1]
        
        x2 = target[0]
        y2 = target[1]
        
        
        #we can't look at ourselves
        if( x1 == x2 and y1 == y2 ):
            return []
        
        
        absx0 = math.fabs(x2 - x1);
        absy0 = math.fabs(y2 - y1);
        

        sgnx0 = util.signum( x2 - x1 );
        sgny0 = util.signum( y2 - y1 );

        
        x = int( x1 );
        y = int( y1 );


        #distance, in tiles, between origin and currently tested tile
        distance = 1

        #this is the list we are going to return at the end
        list_visible_tiles = []
        
        #we add tiles to list with this visibility, if we encounter a partial obstacle, we change this to 1
        #so that all the next tiles we add are partial as well
        visibility = 0
        
        if( absx0 > absy0 ):
            y_x = absy0/absx0;
            D = y_x -0.5;

            for i in xrange( int( absx0 ) ): #@UnusedVariable
                lastx = x
                lasty = y
                
                if( D > 0 ):
                    
                    if( sgny0 == -1 ): y -= 1
                    else: y += 1
                    D -= 1

                if( sgnx0 == 1 ): x += 1
                else: x -= 1

                D += y_x
                
                #=========================TEST==========================================
                list_visible_tiles, visibility = self.testTile( x, y, distance, list_visible_tiles, visibility, lastx, lasty )
                
                distance += 1
            
        #//(y0 >= x0)            
        else:
            x_y = absx0/absy0;
            D = x_y -0.5;

            for i in xrange( int( absy0 ) ): #@UnusedVariable
                lastx = x
                lasty = y
        
                if( D > 0 ):
                    if( sgnx0 == -1 ): x -= 1
                    else: x += 1
                    D -= 1.0
            
                if( sgny0 == 1 ): y += 1
                else: y -= 1
    
                D += x_y
                
                #=========================TEST==========================================
                list_visible_tiles, visibility = self.testTile( x, y, distance, list_visible_tiles, visibility, lastx, lasty )
                
                distance += 1
                
                
        return list_visible_tiles
                

    #tests the tile for visibility
    def testTile(self, x, y, distance, list_visible_tiles, visibility, lastx, lasty ):
        
        #level bounds
        if( self.outOfLevelBounds(x, y) ):
            return( list_visible_tiles, visibility )
        
        #if we can't see here, set visibility to 2, and return
        if( self.level._level_data[x][y] > 1 ):
            visibility = 2
            list_visible_tiles.append( ( (x,y), visibility) )                    
            return( list_visible_tiles, visibility )
        
        #partial view, increase visibility by one 
        if( self.level._level_data[x][y] == 1 ):
            #if this is a tile next the origin, than ignore the partial
            if distance > 1 and visibility < 2:
                    visibility += 1
    
        #diagonal
        if lastx != x and lasty != y:
            
            #if both side tiles are totally blocked, just set visibility to 2 and return
            if self.level._level_data[x][lasty] > 1 and self.level._level_data[lastx][y] > 1:
                visibility = 2
                
            #if both side tiles are partially blocked, set partial visibility
            elif self.level._level_data[x][lasty] == 1 and self.level._level_data[lastx][y] == 1:
                if distance > 1 and visibility < 2:                    
                        visibility += 1
                
            #if one side tile is completely blocked
            elif self.level._level_data[x][lasty] >= 2:
                
                #if other side tile is empty, or partial, treat it as partial cover
                if self.level._level_data[lastx][y] <= 1:
                    if distance > 1 and visibility < 2:                    
                            visibility += 1
                
            #if one side tile is completely blocked
            elif self.level._level_data[lastx][y] >= 2:
                
                #if other side tile is empty, or partial, treat it as partial cover
                if self.level._level_data[x][lasty] <= 1:
                    if distance > 1 and visibility < 2:                    
                            visibility += 1
                
        
        
        list_visible_tiles.append( ( (x,y), visibility) )                    
        return( list_visible_tiles, visibility )



    
    def getLOSHDict(self, position ):
        
        losh_dict = {}
        
        for i in xrange( self.level.maxX ):
            for j in xrange( self.level.maxY ):
                for a in self.getLOS(position, (i,j) ):
                    if( a[1] != 2 ):
                        
                        if a[0] in losh_dict:
                            if( losh_dict[a[0]] > a[1]):
                                losh_dict[a[0]] = a[1]
                        else:
                            losh_dict[a[0]] = a[1]
                            

        return losh_dict
        
               
                

    def getMoveDict(self, unit, returnOrigin = False ):    
                
        final_dict = {}

        open_list = [(unit.pos,unit.ap)]
        
        for tile, actionpoints in open_list:

            for dx in xrange(-1,2):
                for dy in xrange( -1,2 ):            
                    
                    if( dx == 0 and dy == 0):
                        continue
                    
                    
                    #we can't check our starting position
                    if( tile[0] + dx == unit.pos[0] and tile[1] + dy == unit.pos[1] ):
                        continue
                    
                    
                    x = int( tile[0] + dx )
                    y = int( tile[1] + dy )
                    
                    
                    if( self.outOfLevelBounds(x, y) ):
                        continue
                    
                    
                    if( self.canIMoveHere(unit, tile, dx, dy) == False ):
                        continue                   
                    
                    
                    #if we are checking diagonally
                    if( dx == dy or dx == -dy ):
                        ap = actionpoints - 1.5
                    else:
                        ap = actionpoints - 1
                    
                    if( ap < 0 ):
                        continue
                    
                    pt = (x,y) 
                    
                    if pt in final_dict:
                        if( final_dict[pt] < ap ):
                            final_dict[pt] = ap
                            open_list.append( ( pt, ap ) )
                    else: 
                            final_dict[pt] = ap
                            open_list.append( ( pt, ap ) )
                        
                    
        if( returnOrigin ):
            final_dict[unit.pos] = unit.ap
            return final_dict
        
        return final_dict
  
 


    def canIMoveHere(self, unit, position, dx, dy ):
              
        dx = int( dx )
        dy = int( dy )
              
        if( (dx != 1 and dx != 0 and dx != -1) and 
            (dy != 1 and dy != 0 and dy != -1) ):
            notify.critical( "Exception: %s... %s", sys.exc_info()[1], traceback.extract_stack() )
            raise Exception( "Invalid dx (%d) or dy (%d)" %(dy ,dy) )
        
        ptx = int( position[0] )
        pty = int( position[1] )


        #check if the level is clear at that tile
        if( self.level._level_data[ ptx + dx ][ pty + dy ] != 0 ):
            return False
        
        #check if there is a dynamic obstacle in the way
        if( self.dynamic_obstacles[ ptx + dx ][ pty + dy ][0] != DYNAMICS_EMPTY ):
            #ok if it a unit, it may be the current unit so we need to check that
            if( self.dynamic_obstacles[ ptx + dx ][ pty + dy ][0] == DYNAMICS_UNIT ):
                if( self.dynamic_obstacles[ ptx + dx ][ pty + dy ][1] != unit.id ):
                    return False

        
        #check diagonal if it is clear
        if( dx != 0 and dy != 0 ):
            
            #if there is something in level in the way
            if( self.level._level_data[ ptx + dx ][ pty ] != 0 or 
                self.level._level_data[ ptx ][ pty + dy ] != 0 ):
                return False
        
            #check if there is a dynamic thing in the way 
            if( self.dynamic_obstacles[ ptx + dx ][ pty ][0] != DYNAMICS_EMPTY ):
                #see if it is a unit
                if( self.dynamic_obstacles[ ptx + dx ][ pty ][0] == DYNAMICS_UNIT ):
                    #so its a unit, see if it is friendly
                    unit_id = self.dynamic_obstacles[ ptx + dx ][ pty ][1] 
                    if( self.units[unit_id].owner != unit.owner ):
                        return False
                    

            if( self.dynamic_obstacles[ ptx ][ pty + dy ][0] != DYNAMICS_EMPTY ):
                if( self.dynamic_obstacles[ ptx ][ pty + dy ][0] == DYNAMICS_UNIT ):
                    unit_id = self.dynamic_obstacles[ ptx ][ pty + dy ][1] 
                    if( self.units[unit_id].owner != unit.owner ):
                        return False

            
        return True
        


    
    def getPath(self, unit, target_tile ):
        
        #if we are trying to find a path to the tile we are on
        if( target_tile == unit.pos ):
            return[]
            
        
        moveDict = self.getMoveDict(unit, True)

        
        #if target_tile tile is not in the move list, then raise alarm
        if (target_tile in moveDict) == False:
            print "getPath() got an invalid target_tile"
            notify.critical("getPath() got an invalid target tile:%s", target_tile )
            raise Exception( "Trying to move to an invalid target_tile:%s", target_tile )
            
        
        
        x = target_tile[0]
        y = target_tile[1]
        
        
        path_list = [ (target_tile, moveDict[target_tile]) ]
        
        
        while( 1 ):
        
            biggest_ap = ( 0, 0 )
            
            #find a tile with biggest remaining AP next to this one
            for dx in xrange(-1,2):
                for dy in xrange(-1,2):
                    
                    if( dx == 0 and dy == 0 ):
                        continue
                    
                    pt = ( x+dx, y+dy )
                    
                    #check if the point is even in the list
                    if (pt in moveDict) == False:
                        continue
                    
                    
                    #if we can't move here just skip
                    if( self.canIMoveHere( unit, (x,y), dx, dy) == False ):
                        continue
                    
                    #if we are looking at the origin, and we can move there, we just checked that, stop
                    if( x + dx == unit.pos[0] and y + dy == unit.pos[1] ):
                        path_list.reverse()
                        return path_list
                    
                    #finally we can check the tile 
                    if( moveDict[pt] > biggest_ap[1] ):
                        biggest_ap =  (pt, moveDict[pt])
                    
            
            path_list.append( biggest_ap )
            x = biggest_ap[0][0]
            y = biggest_ap[0][1]
        
      
        raise Exception( "hahahah how did you get to this part of code?" )
        
                
    def findUnit(self, unit_id, source):
        if( unit_id in self.units ) == False:
            notify.critical( "Got wrong unit id:%s", unit_id )
            EngMsg.sendErrorMsg( "Wrong unit id.", source )
            return None

        unit = self.units[unit_id]

        #check to see if the owner is trying to move, or someone else
        if unit.owner.connection != source:
            notify.critical( "Client:%s\ttried to do an action with unit that he does not own" % source.getAddress() )
            EngMsg.sendErrorMsg( "You cannot do this to a unit you do not own." )
            return None

        return unit
        
        
    def moveUnit(self, unit_id, new_position, new_heading, source ):

        unit = self.findUnit( unit_id, source )
                
        if not unit:
            return
                
        move_actions = []
        
        #special case if we just need to rotate the unit
        if unit.pos == new_position:
            
            #see if we actually need to rotate the unit
            if unit.rotate( new_heading ):
                move_actions.append( ('rotate', new_heading) )
            #if not, than do nothing
            else:
                return
            
        #otherwise do the whole moving thing
        else:
            try:
                path = self.getPath( unit, new_position )
            except Exception:
                notify.critical( "Exception:%s", sys.exc_info()[1] )
                EngMsg.sendErrorMsg( sys.exc_info()[1], source )
                return   
            
            #everything checks out, do the actual moving
            for tile, ap_remaining in path:
                self.dynamic_obstacles[ int( unit.pos[0] ) ][ int( unit.pos[1] ) ] = ( DYNAMICS_EMPTY, 0 )
                unit.rotate( tile )                
                unit.move( tile, ap_remaining )                
                self.dynamic_obstacles[ int( unit.pos[0] ) ][ int( unit.pos[1] ) ] = ( DYNAMICS_UNIT, unit.id )                
                move_actions.append( ('move', tile ) )
                
                #TODO: krav: ovo nebi trebalo bas svaki korak rucant?!, losh_dict bi trebalo :(
                #we moved a unit so update its move_dict and losh_dict
                unit.move_dict = self.getMoveDict(unit)
                unit.losh_dict = self.getLOSHDict(unit.pos)
                
                
                res = self.checkMovementInterrupt( unit ) 
                if res:
                    move_actions.extend( res )
                    break
                
                #if this is the last tile than apply last orientation change
                if( tile == path[-1][0] ):
                    if unit.rotate( new_heading ):
                        move_actions.append( ('rotate', new_heading) )
                    
                    
                    
            
        EngMsg.move( unit.id, move_actions )
        EngMsg.sendUnit( util.compileUnit(unit) )
            

    
    def checkMovementInterrupt(self, unit ):
        overwatch,detected = self.isMovementInterrupted( unit )        
        ret_actions = []
        
        if detected:
            for enemy in detected:
                unit.owner.list_visible_enemies.append( enemy )
                ret_actions.append( ('detect', util.compileUnit(enemy)) )
                
        if overwatch:
            for enemy in overwatch:
                res = enemy.doOverwatch( unit )
                if res:
                    ret_actions.append( ('overwatch', res ) )
                if not unit.alive:
                    break
            
        return ret_actions
    
    
    def isMovementInterrupted(self, unit):
        
        #we moved this unit, so we need visibilit to every enemy unit, and stop movement if this unit
        #sees anything or if an enemy unit on overwatch sees this unit
        detected = []
        overwatch = []
        
        for player in self.players.itervalues():
            #if this is owning player, skip
            if player == unit.owner:
                continue
        
            #if this is a teammate, skip
            if player.team == unit.owner.team:
                continue
        
            for enemy in player.unitlist:
                if unit.pos in enemy.losh_dict:
                    if enemy.overwatch:
                        overwatch.append( enemy )
                    
                if enemy.pos in unit.losh_dict and enemy not in unit.owner.list_visible_enemies:
                    detected.append( enemy )
                            
        return (overwatch, detected)
            

    def shoot(self, shooter_id, target_id, source ):
        
        return self.units[shooter_id].shoot( self.units[target_id])
        
        shooter = self.findUnit( shooter_id, source )
        
        if not shooter:
            return
        
        if( target_id in self.units ) == False:
            notify.critical( "Got wrong unit id:%s", target_id )
            EngMsg.sendErrorMsg( "Wrong unit id.", source )
            return None

        target = self.units[target_id]

        #check to see if the owner is trying to shoot his own units
        if target.owner.connection == source:
            notify.critical( "Client:%s\ttried to shoot his own unit." % source.getAddress() )
            EngMsg.sendErrorMsg( "You cannot shoot you own units." )
            return None
            
        return shooter.shoot( target )


if __name__ == "__main__":
    me = Engine()
    me.start()