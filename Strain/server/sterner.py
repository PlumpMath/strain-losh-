'''
Created on 16 May 2012

@author: krav
'''
import sys
sys.path.append('./../client')
sys.path.append('./src')
sys.path.append('./../db')
import engine
import threading
import sys
import time
from server_messaging import *
from util import *
from engine import EngineThread
from dbproxyapi import DBProxyApi as DBApi


STERNER_TIME_LIMIT = 0


class LockedDict:
    
    def __init__(self):
        self.lock = threading.Lock()
        
        self.msg_dict = {}
        
        

    def getMyMsgs(self, id ):
        msg = []

        #try to acquire lock
        if not self.lock.acquire( False ):
            return None
            
        try:            
            #if there are no msg for us return
            if id not in self.msg_dict:
                return None
    
            #if the list is empty return
            if not self.msg_dict[id]:
                return None
    
            #if there is a msg, get first and delete it from
            msg = self.msg_dict[id][0]
            self.msg_dict[id] = self.msg_dict[id][1:] 
            
        finally:
            self.lock.release()

        return ( msg, id )

    
    
    def putMsg(self, id, msg):
        #try to acquire lock
        if not self.lock.acquire( False ):
            return None
            
        try:            
            #if there are no msgs for this id create new list
            if id not in self.msg_dict:
                self.msg_dict[id] = [msg]
            else:
                #if there are msgs, append these msg
                self.msg_dict[id].append( msg )
        finally:
            self.lock.release()



    def getAllMsgsDict(self):
        all_msgs = {}
        
        #try to acquire lock
        if not self.lock.acquire( False ):
            return None
        try:            
            all_msgs = self.msg_dict
            self.msg_dict = {}
        finally:
            self.lock.release()
    
        return all_msgs
    

###################################################################################    
###################################################################################    
###################################################################################    
###################################################################################    
class Sterner:
    
    
    def __init__(self):
        self.notify = Notify( 'Sterner.log' )
        
        self.network = Network( self, self.notify )
        self.network.startServer()
        
        self.db_api = DBApi()
        
        
        #LockedDict for distributing messages from network to Engine threads
        self.from_network = LockedDict()
        #LockedDict for sending msgs to network
        self.to_network = LockedDict()
        
        #dict to save logged in players 
        # K: player_id , V: [panda connection, active_game]
        self.logged_in_players = {}
        
        self.test_thread = EngineThread( TEST_GAME_ID, self.from_network, self.to_network, self.notify )
        self.test_thread.start()
        
        self.notify.info( "Sterner started." )
    
        
        self.new_game_queue = collections.deque()
        self.engine_handler = EngineHandlerThread( self.new_game_queue, self.from_network, self.to_network, self.notify )
        self.engine_handler.start()
        
        
        

    
    def start( self ):
        
        t = time.time()
        #-----------================------main loop---------=====================---------
        #-----------================------main loop---------=====================---------
        #-----------================------main loop---------=====================---------
        while True:
        
            self.network.handleConnections()
        
            #get msg from network
            tmp_msg = self.network.readMsg()
            if tmp_msg:
                #print "sterner dobio:",tmp_msg
                msg, source = tmp_msg
                
                #chek if this messge is for sterner or not
                if msg[0] == STERNER_ID:
                    self.handleSternerMsg( msg[1:], source )
                else:
                    self.putMsgOnQueue( msg[0], msg[1:] )
            
            
            #put msgs on network            
            all_msgs = self.to_network.getAllMsgsDict()
            if all_msgs:
                for player_id in all_msgs:
                    for msg in all_msgs[player_id]:
                        try:
                            self.network._sendMsg( msg, self.logged_in_players[ int(player_id) ][0] )
                        except:
                            #print "trazim: %s... svi: %s" % (player_id, str(self.logged_in_players))
                            pass

            
            time.sleep(0.1) 
        
            
            if STERNER_TIME_LIMIT and time.time() - t > STERNER_TIME_LIMIT:
                self.test_thread.stop = True
                break
        #---------================--------main loop--------==================----------
        #---------================--------main loop--------==================----------
        #---------================--------main loop--------==================----------
        
        #shutdown everything we can
        self.test_thread.stop = True        
        self.engine_handler.stop = True
        self.network.stopServer()

        time.sleep(3)
        
    
    def putMsgOnQueue(self, game_id, msg):
        
        #put this message in queue only if there are active games with this id
        for tmp_value in self.logged_in_players.values():
            try:
                if tmp_value[1] == game_id:
                    self.from_network.putMsg(game_id, msg)
                    return
            except:
                pass
            
        print "nisam naso:", game_id, "  msg:", msg
    
    
    def getIdFromConnection(self, connection):
        for player_id in self.logged_in_players:
            if self.logged_in_players[player_id][0] == connection:
                return player_id
        return None
    
    
    
    def handleSternerMsg(self, message, source):
        print "handleSternerMessage message:", message, "   source:", source
        
        if message[0] == STERNER_LOGIN:
            user_data = self.db_api.returnPlayer( message[1] )

            if user_data[3] != message[2]:            
                self.network._sendMsg( (ERROR, "Wrong username/password"), source )
                return
            
            player_id = user_data[0]
            
            #check if this player already logged in, if so disconnect him
            if player_id in self.logged_in_players:
                self.network.disconnect(self.logged_in_players[player_id][0])

            #remember this new player, if this player had some previous connection, in logged_in_players, this will overwrite it                
            self.logged_in_players[ player_id ] = [source]
            
            #send LOGIN_SUCCESS to client
            self.network._sendMsg( (LOGIN_SUCCESS, player_id), source )

            #send all levels and all player_ids to client so he can create new games
            self.network._sendMsg( (ALL_PLAYERS, self.db_api.getAllPlayers()), source )
            self.network._sendMsg( (ALL_LEVELS, self.db_api.getAllLevels()), source )
            self.network._sendMsg( (MY_ACTIVE_GAMES, self.db_api.getMyActiveGames( player_id )), source )
            self.network._sendMsg( (MY_UNACCEPTED_GAMES, self.db_api.getMyUnacceptedGames( player_id )), source )
            self.network._sendMsg( (MY_WAITING_GAMES, self.db_api.getMyWaitingGames( player_id )), source )
            return

                
        elif message[0] == START_NEW_GAME:
            print "+++++new game:", message
            level = message[1]
            budget = message[2]
            player_ids = message[3]
            player_id = self.getIdFromConnection(source)
            
            #check if there are at least 2 players
            if len( player_ids ) < 2:
                self.network._sendMsg( (ERROR, "Not enough players"), source )
                return
            
            #check if level is ok
            all_levels = self.db_api.getAllLevels()
            if level not in all_levels:
                self.network._sendMsg( (ERROR, "Wrong level"), source )
                return
                 
            #TODO: krav: check if budget is ok
            
            #check if player_ids are ok
            all_player_ids = [ int(x) for x,y in self.db_api.getAllPlayers() ]
            for p_id in player_ids:
                if p_id not in all_player_ids:
                    self.network._sendMsg( (ERROR, "Wrong player id:%d"%p_id), source )
                    return


            #create the game and all players in the database, set game creator accept status to 1                    
            game_id = self.db_api.createGame(level, budget, player_id )
            for i in xrange(0, len(player_ids)):
                if player_ids[i] == player_id:
                    self.db_api.addPlayerToGame(game_id, player_ids[i], i, i, 1)
                else:
                    self.db_api.addPlayerToGame(game_id, player_ids[i], i, i, 0)
            
            #set acceptance status of creator to accepted
            game_player = self.db_api.getGamePlayer(game_id, player_id)
            game_player[5] = 1
            self.db_api.updateGamePlayer(game_player)
            
            
            #TODO: 0: prvo stavit sve u bazu ako se tred ne digne da moze kasnije sve procitat iz baze
            self.new_game_queue.append( (game_id, self.getIdFromConnection(source), level, budget, player_ids ) )
            return
                
                
        elif message[0] == ALL_FINISHED_GAMES:
            self.network._sendMsg( (ALL_FINISHED_GAMES, self.db_api.getAllFinishedGames()), source )
            return
                
                
        elif message[0] == REFRESH_MY_GAME_LISTS:
            self.network._sendMsg( (ALL_PLAYERS, self.db_api.getAllPlayers()), source )
            self.network._sendMsg( (ALL_LEVELS, self.db_api.getAllLevels()), source )            
            self.network._sendMsg( (MY_ACTIVE_GAMES, self.db_api.getMyActiveGames( player_id )), source )
            self.network._sendMsg( (MY_UNACCEPTED_GAMES, self.db_api.getMyUnacceptedGames( player_id )), source )
            self.network._sendMsg( (MY_WAITING_GAMES, self.db_api.getMyWaitingGames( player_id )), source )
            return
                
                
        elif message[0] == MY_UNACCEPTED_GAMES:
            player_id = self.getIdFromConnection(source)
            self.network._sendMsg( (MY_UNACCEPTED_GAMES, self.db_api.getMyUnacceptedGames( player_id )), source )
            return
                
                
        elif message[0] == ACCEPT_GAME:
            game_id = message[1]
            player_id = self.getIdFromConnection(source)

            #check if this game already started or is finished            
            game = self.db_api.getGame(game_id)
            if game[5] == 1:
                self.network._sendMsg( (ERROR, "Game already started"), source )
                return
            elif game[5] == 2:
                self.network._sendMsg( (ERROR, "Game finished"), source )
                return
                
            #check if this player really did not accept this game yet
            game_player = self.db_api.getGamePlayer(game_id, player_id)
            if game_player[5] == 1:
                self.network._sendMsg( (ERROR, "Already accepted this game"), source )
                return
            
            #update this player's acceptance
            game_player[5] = 1
            self.db_api.updateGamePlayer( game_player )
            
            #we can accept this game
            self.network._sendMsg( (ACCEPT_GAME, game_id), source )

            #try to see if this is the last player accepting and if so start the game            
            #if at least 1 player did not accept, return
            for player in self.db_api.getGameAllPlayers( game_id ):
                if player[5] == 0:
                    return 
            
            #ok all players accepted, start this game
            game[6] = 1
            self.db_api.updateGame(game)
            return
                
                
        elif message[0] == ENTER_GAME:
            player_id = self.getIdFromConnection(source)
            self.logged_in_players[player_id] = self.logged_in_players[player_id][:1] 
            self.logged_in_players[player_id].append( message[1] )
            return


        elif message[0] == PING:
            self.network._sendMsg( (PONG, time.time()), source )
            return

        else:
            self.notify.error("Undefined message:%s", str(message))

        pass
                
                

    def playerDisconnected(self, source):

        #go through all logged in players
        for pid in self.logged_in_players:
            
            #if we find the one with this connection
            if self.logged_in_players[ pid ][0] == source:
                
                #remove him from the dict
                del self.logged_in_players[ pid ]
                
                #TODO: 0: remove all his messages from network queues
                return

    
    
#########################################################################################################
#########################################################################################################
#########################################################################################################
#########################################################################################################
class EngineHandlerThread( threading.Thread ):
    
    def __init__( self, new_game_queue, from_network, to_network, notify ):
        threading.Thread.__init__(self)
        
        self.name = "EngineHadlerThread"
        
        self.new_game_queue = new_game_queue
        self.from_network = from_network
        self.to_network = to_network
        self.notify = notify

        #main dict where we will hold engine threads k:game_id, v:engine thread
        self.engine_threads = {}
        
        self.setDaemon(True)
        self.stop = False
        
        pass
    
    
    def run(self):
        
        while True:

            if self.stop:
                self.stopAllThreads()
                break

            try:
                msg = self.new_game_queue.pop()
                
                game_id = msg[0]
                creator_id = msg[1]
                map = msg[2]
                budget = msg[3]
                players = msg[4]
                
                #create new thread
                tmp_thread = EngineThread( game_id, self.from_network, self.to_network, self.notify, False, map, budget, players )
                tmp_thread.start()
                
                self.engine_threads[game_id] = tmp_thread
 
                #TODO: 1: ovdje prvo provjerit jel se fakat startao gejm pa onda tek poslat poruku
                self.to_network.putMsg(creator_id, (NEW_GAME_STARTED, game_id) )
                
            except IndexError:
                pass
                

            
            time.sleep(0.1)
        
        
    def stopAllThreads(self):
        for thr in self.engine_threads.values():
            thr.stop = True
    

